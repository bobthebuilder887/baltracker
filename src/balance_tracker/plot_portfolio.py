import argparse
from decimal import Decimal
from typing import Sequence

import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import pandas as pd

from balance_tracker import balances


def read_data(path="portfolio.csv", sample_interval: str = "5min") -> pd.Series:
    df = pd.read_csv(
        filepath_or_buffer=path,
        header=None,
    )
    df.columns = ["timestamp", "value_usd"]
    df = df.astype({"value_usd": float, "timestamp": int})
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")
    df = df.set_index("timestamp")
    df = df.resample(sample_interval)["value_usd"].last().ffill()
    return df


def read_token_balances(path):
    all_balances = balances.read_all_balances(path)

    # covalent.Chains.__members__

    # Get all unique contracts
    cas: set[str] = set()
    for s in map(lambda b: set(b["token_balances"].keys()), all_balances):
        cas |= s

    # Get balance data
    bal_data: list[dict[str, Decimal]] = []
    for bal in map(lambda b: b["token_balances"], all_balances):
        record: dict[str, Decimal] = {}
        for ca, token_info in bal.items():
            record[ca] = token_info["balance"]
        bal_data.append(record)

    # Get value data
    val_data: list[dict[str, Decimal]] = []
    for bal in map(lambda b: b["token_balances"], all_balances):
        record: dict[str, Decimal] = {}
        for ca, token_info in bal.items():
            record[ca] = token_info["value"]
        val_data.append(record)

    # Make a ts-based index
    # idx = pd.DatetimeIndex(
    #     data=map(
    #         lambda b: pd.to_datetime(
    #             b["timestamp"],
    #             unit="s",
    #         ),
    #         all_balances,
    #     ),
    # )

    # bal_df = pd.DataFrame(columns=list(cas), index=idx, data=bal_data).fillna(0)  # type: ignore
    # val_df = pd.DataFrame(columns=list(cas), index=idx, data=val_data).fillna(0)  # type: ignore
    # Create filters for trades, withdrawals and deposits
    # increase = (bal_df.astype(float).diff() < 0).sum(axis=1) > 0
    # decrease = (bal_df.astype(float).diff() > 0).sum(axis=1) > 0

    # TODO: make sure to filter out deposit and withdrawal pnl change
    # TODO: need to suppport aptos and pump.fun for more in-depth analysis
    # trades = increase & decrease
    # deposits = increase & ~decrease
    # withdrawals = ~increase & decrease

    # val_df["total"] = val_df.sum(axis=1)


def calc_returns(data: pd.Series) -> pd.Series:
    data = 100 * (data - data.iloc[0]) / data.iloc[0]
    return data


def calc_sharpe(returns: pd.Series, risk_free_rate: float = 0.0) -> float:
    return (returns.sum() - risk_free_rate) / (returns - risk_free_rate).std()


def plot_data(
    data: pd.Series,
    time_interval: str | None = None,
    plot_pct: bool = True,
) -> None:
    if plot_pct:
        title = f"Portfolio cumulative % returns over {data.index.freqstr} intervals"
        ylabel = "% returns"
        data = calc_returns(data)
    else:
        title = "Portfolio USD value over 5min intervals"
        ylabel = "USD"

    if time_interval is not None:
        interval = pd.Timedelta(time_interval)
        title += f" (last {time_interval})"
    else:
        interval = data.index.max() - data.index.min()  # type: ignore
        title += " (since inception)"

    data = data[data.index > data.index.max() - interval]

    data.plot(
        kind="line",
        grid=True,
        title=title,
        xlabel="Time, UTC",
        ylabel=ylabel,
    )

    min = data.index.max() - interval  # type: ignore
    delta = data.index.max() - min
    plt.grid(True, which="both")
    plt.xlim([min, data.index.max() + 0.05 * delta])  # type: ignore
    plt.ylim([data.min() - 0.05 * data.min(), data.max() + 0.05 * data.max()])  # type: ignore

    # enable smaller ticks
    plt.xticks(fontsize=8, minor=True)
    plt.yticks(fontsize=8, minor=True)

    # add labels for smaller increments
    plt.gca().xaxis.set_minor_locator(ticker.AutoMinorLocator())
    plt.gca().yaxis.set_minor_locator(ticker.AutoMinorLocator())

    plt.minorticks_on()
    plt.tick_params(axis="both", which="minor", labelsize=6)

    plt.tight_layout()

    try:
        plt.show()
    except KeyboardInterrupt:
        pass


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Plot portfolio data")

    parser.add_argument(
        "-d",
        "--data_path",
        default="./.data/portfolio.csv",
        help="Path to portfolio data file",
    )
    parser.add_argument(
        "-t",
        "--time_interval",
        type=str,
        default=None,
        help="Time interval for plot (e.g., 24h, 72h, 7d, etc.)",
    )
    parser.add_argument(
        "-s",
        "--sample_interval",
        type=str,
        default="5min",
        help="Time interval for data samples (e.g., 5min, 1h, etc.)",
    )
    parser.add_argument(
        "-p",
        "--plot_pct",
        action="store_true",
        help="Plot percentage returns instead of absolute values",
    )

    args = parser.parse_args()

    data = read_data(path=args.data_path, sample_interval=args.sample_interval)
    plot_data(
        data=data,
        time_interval=args.time_interval,
        plot_pct=args.plot_pct,
    )
    exit(0)


if __name__ == "__main__":
    main()
