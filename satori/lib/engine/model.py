# WIP
# This is the core of the engine - building models continuously to search for the best one
# its reactive, but needs better architecture to support a more modular design.
# the only option people have right now is to extend the object with overrides, using
# their own algorithms, but that basically means rewriting the whole thing.
# it needs better modularity, and perhaps should make use of sci-kit learn's pipelines.
'''
Basic Reponsibilities of the ModelManager:
1. keep a record of the datasets, features, and parameters of the best model.
2. retrain the best model on new data available, generate and report prediction.
3. continuously generate new models to attempt to find a better one.
    A. search the parameter space smartly
    B. search the engineered feature space smartly
    C. evaluate new datasets when they become available
4. save the best model details and load them upon restart
'''
import os
import copy
import time
import random
import numpy as np
import pandas as pd
import datetime as dt
from itertools import product
from functools import partial
from reactivex.subject import BehaviorSubject
from sklearn.exceptions import NotFittedError
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error
import ppscore
from xgboost import XGBRegressor, XGBClassifier

from satori.lib.apis import disk, memory
from satori import config
from .structs import HyperParameter, SourceStreamTargets


class ModelManager:

    def __init__(
        self,
        modelPath:str=None,
        hyperParameters:'list(HyperParameter)'=None,
        metrics:dict=None,
        features:dict=None,
        chosenFeatures:'list(str)'=None,
        pinnedFeatures:'list(str)'=None,
        exploreFeatures:bool=True,
        sourceId:str='',
        streamId:str='',
        targetId:str='',
        targets:list[SourceStreamTargets]=None,
        split:'int|float'=.2,
        override:bool=False,
    ):
        '''
        modelPath: the path of the model
        hyperParameters: a list of HyperParameter objects
        metrics: a dictionary of functions that each produce
                    a feature (from 1 dynamic column)
                    example: year over year, rolling average
        features: a dictionary of functions that each take in
                    multiple columns of the raw data and ouput
                    a feature (cols known ahead of time)
                    example: high minus low, x if y > 1 else 2**z
        chosenFeatures: list of feature names to start with
        pinnedFeatures: list of feature names to keep in model
        exploreFeatures: change features or not
        id: column name of response variable
        split: train test split percentage or count
        override: override the existing model saved to disk if there is one
        '''
        self.sourceId = sourceId
        self.streamId = streamId
        self.targetId = targetId
        self.modelPath = modelPath or config.root('..', 'models', self.sourceId, self.streamId, self.targetId + '.joblib')
        #self.sources = {'source': {'stream':['targets']}}
        self.targets:list[SourceStreamTargets] = targets
        self.id = SourceStreamTargets(source=sourceId, stream=streamId, targets=[targetId])
        self.hyperParameters = hyperParameters or []
        self.chosenFeatures = chosenFeatures or []
        self.pinnedFeatures = pinnedFeatures or []
        self.scoredFeatures = {}
        self.features = features or {}
        self.metrics = metrics
        self.exploreFeatures = exploreFeatures
        self.testFeatures = self.chosenFeatures
        self.split = split
        self.featureData = {}
        self.xgbInUse = False
        self.xgb = None
        self.setupFlags()
        if not override:
            self.load()
        self.get()
        self.produceFeatureStructure()
        if not self.data.empty:
            self.produceFeatureSet()
        self.syncManifest()

    def overview(self):
        return {
            'source': self.sourceId,
            'stream': self.streamId, 
            'target': self.targetId, 
            'value': self.current.values[0][0] if hasattr(self, 'current') else '',
            'prediction': self.prediction if hasattr(self, 'prediction') else '',
            # this isn't the accuracy we really care about (historic accuracy), 
            # it's accuracy of this current model on historic data.
            'accuracy': f'{str(self.stable*100)[0:5]} %' if hasattr(self, 'stable') else '', 
            'subscribers':'none'}

    def syncManifest(self):
        manifest = config.get('manifest') or {}
        manifest[self.key()] = {
            'targets': [x.asTuples() for x in self.targets], 
            'purged': manifest.get(self.key(), {}).get('purged', [])}
        config.put('manifest', data=manifest)

    ### FLAGS ################################################################################
    
    def setupFlags(self):
        self.modelUpdated = BehaviorSubject(None)
        self.targetUpdated = BehaviorSubject(None)
        self.inputsUpdated = BehaviorSubject(None)
        self.predictionUpdate = BehaviorSubject(None)
        self.predictionEdgeUpdate = BehaviorSubject(None)
        self.newAvailableInput = BehaviorSubject(None)
    
    ### STATIC FEATURES GENERATORS ###########################################################

    @staticmethod
    def rawDataMetric(df:pd.DataFrame=None, column:tuple=None) -> pd.Series:
        def name() -> tuple:
            return column
        
        if df is None:
            return name()
        feature = df.loc[:, column]
        feature.name = name()
        return feature

    @staticmethod
    def dailyPercentChangeMetric(
        df:pd.DataFrame=None,
        column:tuple=None,
        prefix:str='Daily',
        yesterday:int=1,
    ) -> pd.Series:

        def name() -> tuple:
            return tuple([col for col in column[0:len(column)-1]]) + (prefix+column[len(column)-1]+str(yesterday),) 

        if df is None:
            return name()
        feature = df.loc[:, column].shift(yesterday-1) / df.loc[:, column].shift(yesterday)
        feature.name = name()
        return feature

    @staticmethod
    def rollingPercentChangeMetric(
        df:pd.DataFrame=None,
        column:tuple=None,
        prefix:str='Rolling',
        window:int=2,
        transformation:str='max',
    ) -> pd.Series:
        
        def name() -> tuple:
            return tuple([col for col in column[0:len(column)-1]]) + (prefix+column[len(column)-1]+str(window)+transformation.replace('(','').replace(')',''),) 

        if df is None:
            return name()
        transactionOptions = 'sum max min mean median std count var skew kurt quantile cov corr apply'
        if (isinstance(window, int)
            and transformation.startswith(tuple(transactionOptions.split()))):
            feature = df[column] / eval(f'df[column].shift(1).rolling(window={window}).{transformation}')
            feature.name = name()
            return feature

        raise Exception('eval call on transformation failed, unable to create feature')
   

    ### GET DATA ####################################################################
    
    #@staticmethod
    #def addFeatureLevel(df:pd.DataFrame):
    #    ''' adds a feature level to the multiindex columns'''
    #    return pd.MultiIndex.from_tuples([c + ('Raw',)  for c in df.columns])

    def get(self):
        ''' gets the raw data from disk '''
        
            
        def handleEmpty():
            '''
            todo: what should we do if no data available yet? 
            should self.data be None? or should it be an empty dataframe without our target columns?
            or should it be an empty dataframe with our target columns?
            It seems like it should just be None and that we should halt behavior until it has a
            threshold amount of data.
            '''
            self.data = self.data if self.data is not None else pd.DataFrame(
                {x: [] for x in SourceStreamTargets.combine(self.targets)})
    
        self.data = disk.Api().gather(sourceStreamTargetss=self.targets, targetColumn=self.id.id)
        handleEmpty()

    ### TARGET ####################################################################

    def produceTarget(self):
        series = self.data.loc[:, self.id.id()].shift(-1)
        self.target = pd.DataFrame(series)

    def key(self):
        return self.id.id()
    
    def streamKey(self):
        return self.id.id()

    ### FEATURES ####################################################################

    def produceFeatureStructure(self):
        self.features = {
            **self.features,
            **{
            metric(column=col): partial(metric, column=col)
            for metric, col in product(self.metrics.values(), self.data.columns)}
        }

    def produceFeatureSet(self):
        producedFeatures = []
        for feature in self.chosenFeatures:
            fn = self.features.get(feature)
            if callable(fn):
                producedFeatures.append(fn(self.data))
        if len(producedFeatures) > 0:
            self.featureSet = pd.concat(
                producedFeatures,
                axis=1,
                keys=[s.name for s in producedFeatures])
            
    def produceTestFeatureSet(self, featureNames:'list[str]'=None):
        producedFeatures = []
        for feature in featureNames or self.testFeatures:
            fn = self.features.get(feature)
            if callable(fn):
                producedFeatures.append(fn(self.data))
        if len(producedFeatures) > 0:
            self.testFeatureSet = pd.concat(
                producedFeatures,
                axis=1,
                keys=[s.name for s in producedFeatures])

    def produceEvalFeatureSet(self, featureNames:'list[str]'):
        producedFeatures = []
        for feature in featureNames or self.testFeatures:
            fn = self.features.get(feature)
            if callable(fn):
                producedFeatures.append(fn(self.data))
        if len(producedFeatures) > 0:
            return pd.concat(
                producedFeatures,
                axis=1,
                keys=[s.name for s in producedFeatures])

    def produceFeatureImportance(self):
        self.featureImports = {
            name: fimport
            for fimport, name in zip(self.xgbStable.feature_importances_, self.featureSet.columns)
        } if self.xgbStable else {}

    def leastValuableFeature(self):
        if len(self.xgbStable.feature_importances_) == len(self.chosenFeatures):
            matched = [(val, idx) for idx, val in enumerate(self.xgbStable.feature_importances_)]
            candidates = []
            for pair in matched:
                if pair[0] not in self.pinnedFeatures:
                    candidates.append(pair)
            if len(candidates) > 0:
                return self.chosenFeatures[min(candidates)[1]]
        return None

    def scoreFeatures(self, df:pd.DataFrame = None) -> dict:
        ''' generates a predictive power score for each column in df '''
        df = df if df is not None else self.featureSet
        if self.target.columns[0] in df.columns:
            df = df.drop(self.target.columns[0], axis=1)
        df = pd.concat([df, self.target], axis=1)
        return {
            v['x']: v['ppscore']
            for v in ppscore.predictors(
                df,
                y=self.key(),
                output='df',
                sorted=True,
                sample=None)[['x', 'ppscore']].T.to_dict().values()}


    ### FEATURE DATA ####################################################################

    def produceFeatureData(self):
        '''
        produces our feature data map:
        {feature: (feature importance, [raw inputs])}
        '''
        for k in self.featureSet.columns:
            self.featureData[k] = (
                self.featureImports[k], # KeyError: ('streamrSpoof', 'simpleEURCleanedHL', 'RollingHigh43median')
                self.featureData[k][1] if k in self.featureData.keys() else [] + (
                    self.features[k].keywords.get('columns', None)
                    or [self.features[k].keywords.get('column')]))

    def showFeatureData(self):
        '''
        returns true raw feature importance
        example: {
            'Close': 0.6193444132804871,
            'High': 0.16701968474080786,
            'Low': 0.38159190578153357}
        '''
        rawImportance = {}
        for importance, features in self.featureData.values():
            for name in features:
                rawImportance[name] = (importance / len(features)) + rawImportance.get(name, 0)
        return rawImportance

    ### CURRENT ####################################################################

    def producePredictable(self):
        if self.featureSet.shape[0] > 0:
            self.current = pd.DataFrame(self.featureSet.iloc[-1,:]).T#.dropna(axis=1)
            #print('\nself.data\n', self.data.tail(2))
            #print('\nself.featureSet\n', self.featureSet.tail(2))
            #print('\nself.current\n', self.current)
            #print('\nself.prediction\n', self.prediction)

    def producePrediction(self):
        return self.xgb.predict(self.current)[0]

    ### TRAIN ######################################################################

    def produceTrainingSet(self):
        df = self.featureSet.copy()
        df = df.iloc[0:-1,:]
        df = df.replace([np.inf, -np.inf], np.nan)
        df = df.reset_index(drop=True)
        self.trainX, self.testX, self.trainY, self.testY = train_test_split(
            df, self.target.iloc[0:df.shape[0], :], test_size=self.split or 0.2, shuffle=False)

    def produceTestTrainingSet(self):
        df = self.testFeatureSet.copy()
        df = df.iloc[0:-1,:]
        df = df.replace([np.inf, -np.inf], np.nan)
        df = df.reset_index(drop=True)
        self.trainXtest, self.testXtest, self.trainYtest, self.testYtest = train_test_split(
            df, self.target.iloc[0:df.shape[0], :], test_size=self.split or 0.2, shuffle=False)

    def produceFit(self):
        self.xgbInUse = True
        if all(isinstance(y[0], (int, float)) for y in self.trainY.values):
            self.xgb = XGBRegressor(**{param.name: param.value for param in self.hyperParameters})
        else:
            # todo: Classifier untested
            self.xgb = XGBClassifier(**{param.name: param.value for param in self.hyperParameters})
        self.xgb.fit(
            self.trainX,
            self.trainY,
            eval_set=[(self.trainX, self.trainY), (self.testX, self.testY)],
            eval_metric='mae',
            early_stopping_rounds=200,
            verbose=False)
        #self.xgbStable = copy.deepcopy(self.xgb) ## didn't fix it.
        self.xgbStable = self.xgb
        self.xgbInUse = False

    def produceTestFit(self):
        if all(isinstance(y[0], (int, float)) for y in self.trainY.values):
            self.xgbTest = XGBRegressor(**{param.name: param.test for param in self.hyperParameters})
        else:
            # todo: Classifier untested
            self.xgbTest = XGBClassifier(**{param.name: param.value for param in self.hyperParameters})
        self.xgbTest.fit(
            self.trainXtest,
            self.trainYtest,
            eval_set=[(self.trainXtest, self.trainYtest), (self.testXtest, self.testYtest)],
            eval_metric='mae',
            early_stopping_rounds=200,
            verbose=False)

    ### META TRAIN ######################################################################

    def produceTestHyperParameters(self):
        def radicallyRandomize():
            for param in self.hyperParameters:
                x = param.min + (random.random() * (param.max - param.min))
                if param.kind == int:
                    x = int(x)
                param.test = x

        def incrementallyRandomize():
            for param in self.hyperParameters:
                x = (
                    (random.random() * param.limit * 2) +
                    (param.value - param.limit))
                if param.min < x < param.max:
                    if param.kind == int:
                        x = int(round(x))
                    param.test = x

        x = random.random()
        if x >=.9:
            radicallyRandomize()
        elif .1 < x < .9:
            incrementallyRandomize()

    def produceTestFeatures(self):
        ''' sets testFeatures to a list of feature names '''
        def preservePinned():
            self.testFeatures.extend([
                feature for feature in self.pinnedFeatures
                if feature not in self.testFeatures])

        def radicallyRandomize():
            count = min(max(len(self.chosenFeatures) + 2, 1), len(self.features))
            maxCount = len(list(self.features.keys()))
            if maxCount > count * 5:
                evalScores = generateEvalScores(possibleFeatures=list(self.features.keys()), count=count*5)
                self.testFeatures = [evalScores[i][0] for i in range(0, count)]
            else:
                self.testFeatures = list({
                    random.choice(list(self.features.keys()))
                    for _ in range(0, count)})

        def dropOne():
            if len(self.chosenFeatures) >= 2:
                choice = self.leastValuableFeature() or random.choice(self.chosenFeatures)
                self.testFeatures = [f for f in self.chosenFeatures if f != choice]
            else:
                self.testFeatures = self.chosenFeatures

        def addOne():
            notChosen = [f for f in self.features.keys() if f not in self.chosenFeatures]
            if len(notChosen) > 100:
                evalScores = generateEvalScores(notChosen)
                self.testFeatures = self.chosenFeatures + [evalScores[0][0]]
            elif len(notChosen) > 0:
                self.testFeatures = self.chosenFeatures + [random.choice(notChosen)]
            else:
                self.testFeatures = self.chosenFeatures

        def replaceOne():
            notChosen = [f for f in self.features.keys() if f not in self.chosenFeatures]
            if len(notChosen) == 0 or len(self.chosenFeatures) == 0:
                self.testFeatures = self.chosenFeatures
            else:
                if len(notChosen) > 100:
                    evalScores = generateEvalScores(notChosen)
                    addChoice = evalScores[0][0]
                elif len(notChosen) > 0:
                    addChoice = random.choice(notChosen)
                dropChoice = self.leastValuableFeature() or random.choice(self.chosenFeatures)
                self.testFeatures = self.chosenFeatures + [addChoice]
                self.testFeatures = [f for f in self.testFeatures if f != dropChoice]

        def generateEvalScores(possibleFeatures:'list[str]', count:int=None):
            count = count or min(20, round(len(possibleFeatures)*0.05))
            evalSet = self.produceEvalFeatureSet(
                featureNames=list(set([random.choice(possibleFeatures) for _ in range(0, count)])))
            evalSet = evalSet.replace([np.inf, -np.inf], np.nan)
            evalScores = self.scoreFeatures(evalSet)
            self.scoredFeatures = {**self.scoredFeatures, **evalScores}
            evalScores = list(evalScores.items())
            evalScores.sort(key=lambda x:x[1])
            evalScores.reverse()
            return evalScores

        if self.exploreFeatures:
            x = random.random()
            if x >=.9:
                radicallyRandomize()
            elif x >=.7:
                replaceOne()
            elif x >=.5:
                addOne()
            elif x >=.3:
                dropOne()
            else:
                self.testFeatures = self.chosenFeatures
        else:
            self.testFeatures = self.chosenFeatures
        preservePinned()

    def evaluateCandidate(self):
        ''' notice, model consists of the hyperParameter values and the chosenFeatures '''
        self.stable = self.xgb.score(self.testX, self.testY)
        self.test = self.xgbTest.score(self.testXtest, self.testYtest)
        # not sure what this score is... r2 f1? not mae I think
        if self.stable < self.test:
            for param in self.hyperParameters:
                param.value = param.test
            self.chosenFeatures = self.testFeatures
            self.featureSet = self.testFeatureSet
            self.save()
            return True
        return False
    
    ### SAVE ###########################################################################

    def save(self):
        ''' save the current model '''
        disk.ModelApi.save(self.xgb, self.modelPath, self.hyperParameters, self.chosenFeatures)
        
    def load(self): # -> bool:
        ''' loads the model - happens on init so we automatically load our progress '''
        xgb = disk.ModelApi.load(self.modelPath)
        if xgb == False:
            return False
        if (
            all([scf in self.features.keys() for scf in xgb.savedChosenFeatures]) and
            True # all([shp in self.hyperParameters for shp in xgb.savedHyperParameters])
        ):
            self.xgb = xgb
            self.hyperParameters = self.xgb.savedHyperParameters
            self.chosenFeatures = self.xgb.savedChosenFeatures
        return True

    ### MAIN PROCESSES #################################################################

    def buildStable(self):
        if self.data is not None and not self.data.empty and self.data.shape[0] > 20:
            self.produceTarget()
            self.produceFeatureStructure()
            self.produceFeatureSet()
            self.producePredictable()
            self.produceTrainingSet()
            self.produceFit()
            self.produceFeatureImportance()
            self.produceFeatureData()
            return True
        return False

    def buildTest(self):
        self.produceTestFeatures()
        self.produceTestFeatureSet()
        self.produceTestTrainingSet()
        self.produceTestHyperParameters()
        self.produceTestFit()
    
    ### LIFECYCLE ######################################################################
    
    def runPredictor(self):
        def makePrediction(isTarget=False):
            if isTarget and self.buildStable():
                self.prediction = self.producePrediction()
                print(f'self.prediction - {self.streamId} {self.targetId}:', self.prediction)
                self.predictionUpdate.on_next(self)
            ## this is a feature to be added - a second publish stream which requires a
            ## different dataset - one where the latest update is taken into account.
            #    if self.edge: 
            #        self.predictionEdgeUpdate.on_next(self)
            #elif self.edge:
            #    self.buildStable()
            #    self.predictionEdge = self.producePrediction()
            #    self.predictionEdgeUpdate.on_next(self)
        
        def makePredictionFromNewModel():
            print(f'model updated - {self.streamId} {self.targetId}:', self.stable, self.test)
            makePrediction()
        
        def makePredictionFromNewInputs(incremental):
            self.data = memory.appendInsert(
                df=self.data, 
                incremental=incremental)
            makePrediction()
            
        def makePredictionFromNewTarget(incremental):
            for col in incremental.columns:
                if col not in self.data.columns:
                    incremental = incremental.drop(col, axis=1)
            #incremental.columns = ModelManager.addFeatureLevel(df=incremental)
            self.data = memory.appendInsert(
                df=self.data, 
                incremental=incremental)
            makePrediction(isTarget=True)
                
        self.modelUpdated.subscribe(lambda x: makePredictionFromNewModel() if x is not None else None)
        self.inputsUpdated.subscribe(lambda x: makePredictionFromNewInputs(x) if x is not None else None)
        self.targetUpdated.subscribe(lambda x: makePredictionFromNewTarget(x) if x is not None else None)
        
    def runExplorer(self):
        if hasattr(self, 'target') and hasattr(self, 'xgbStable'):
            try:
                self.buildTest()
                if self.evaluateCandidate():
                    self.modelUpdated.on_next(True)
            except NotFittedError as e:
                '''
                this happens on occasion...
                maybe making  self.xgbStable a deepcopy would fix
                '''
                #print('not fitted', e)
                pass
            #except AttributeError as e:
            #    ''' 
            #    this happens at the beginning of running when we have not set
            #    self.xgbStable yet.
            #    
            #    '''
            #    #print('Attribute', e)
            #    pass
            ##except Exception as e:
            ##    print('UNEXPECTED', e)
        else:
            time.sleep(1)
    
    def syncAvailableInputs(self):
        
        def sync(x):
            '''
            add the new datastreams and histories to the top 
            of the list of things to explore and evaluate 
            '''
            ## something like this?
            #self.features.append(x)
            # 
            #self.targets.append(SourceStreamTargets(x))  or something
            #self.syncManifest()  then sync manifest when you change targets.
            #maybe remove targets that aren't being used as any features.. somewhere?
            
        self.newAvailableInput.subscribe(lambda x: sync(x) if x is not None else None)


def show(name, value):
    if isinstance(value, pd.DataFrame):
        print(f'\n{name}\n', value.tail(2))
    else:
        print(f'\n{name}\n', value)