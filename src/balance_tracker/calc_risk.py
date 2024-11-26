import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns


def usd_to_crypto(usd, price):
    return usd / price


def risk_estimate(pr_win: float, frac_loss: float, frac_gain: float, frac: float = 0.5):
    return frac * kelly_criterion_bin(pr_win, frac_loss, frac_gain)


def solve_frac_gain(
    pr_win: float,
    frac_loss: float,
    frac_gain: float,
    frac: float = 0.5,
):
    """Calculate what is  the point at which it makes sense to start taking profits"""
    pass


def kelly_criterion_bin(pr_win: float, frac_loss: float, frac_gain: float) -> float:
    """Binary outcomes"""
    pr_loss = 1 - pr_win
    fraction = pr_win / frac_loss - pr_loss / frac_gain

    return fraction


def optimal_grid():
    LOSS = 0.7

    # 50% to 1000%
    payout_frac = np.arange(0.8, 1.55, 0.05)
    pr_win = np.arange(0.3, 0.7, 0.03)

    kelly = []
    for frac in payout_frac:
        kelly_row = []
        for pr in pr_win:
            kelly_row.append(kelly_criterion_bin(pr, LOSS, frac))
        kelly.append(kelly_row)

    grid = np.array(kelly)

    sns.heatmap(
        data=grid.round(3),
        annot=True,
        fmt=".2f",
        vmin=0,
        cmap="YlGnBu",
        xticklabels=pr_win.round(2).astype(str),
        yticklabels=payout_frac.round(2).astype(str),
    )

    plt.show()


def main() -> None:
    from decimal import Decimal

    from icecream import ic

    from balance_tracker.api_req import get_gecko_price
    from balance_tracker.plot_portfolio import read_data

    def get_pr_win() -> float:
        try:
            pr_win = float(input("Enter probability of win: "))
        except ValueError:
            return get_pr_win()
        return pr_win

    def get_gain() -> float:
        try:
            gain = float(input("Enter gain on capital: "))
        except ValueError:
            return get_gain()
        return gain

    # TODO: turn into cli
    PORTFOLIO_USD: Decimal = Decimal(read_data().iloc[-1])
    FRAC: float = 1 / 3
    CURRENCY: str = "solana"
    FRAC_LOSS: float = 0.7
    FRAC_GAIN: float = get_gain()
    PR_WIN: float = get_pr_win()

    estimate: Decimal = Decimal(
        risk_estimate(
            pr_win=ic(PR_WIN),
            frac_loss=ic(FRAC_LOSS),
            frac_gain=ic(FRAC_GAIN),
            frac=ic(FRAC),
        )
    )

    print("bet", ic(PORTFOLIO_USD) * ic(estimate), "USD")
    print("bet", PORTFOLIO_USD * estimate / get_gecko_price(CURRENCY), CURRENCY)


if __name__ == "__main__":
    main()
