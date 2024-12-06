import argparse
from typing import Sequence

import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import pandas as pd


def read_data(path, sample_interval: str) -> pd.Series:
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


def calc_returns(data: pd.Series) -> pd.Series:
    data = 100 * (data - data.iloc[0]) / data.iloc[0]
    return data


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
        title = f"Portfolio USD value over {data.index.freqstr} intervals"
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
        default="10min",
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
