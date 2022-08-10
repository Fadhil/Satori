defmodule Satori.Repo.Migrations.CreateWallets do
  use Ecto.Migration

  def change do
    create table(:wallets) do
      add :user_id, :integer
      add :address, :string
      add :public_key, :string

      timestamps()
    end
  end
end
