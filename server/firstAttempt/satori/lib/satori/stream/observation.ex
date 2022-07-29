defmodule Satori.Stream.Observation do
  use Ecto.Schema
  import Ecto.Changeset

  schema "observation" do
    field :source_id, :integer
    field :stream_id, :integer
    field :target_id, :integer
    field :value, :string
    field :wallet_id, :integer

    timestamps()
  end

  @doc false
  def changeset(observation, attrs) do
    observation
    |> cast(attrs, [:source_id, :stream_id, :target_id, :wallet_id, :value])
    |> validate_required([:source_id, :stream_id, :target_id, :wallet_id, :value])
  end
end
