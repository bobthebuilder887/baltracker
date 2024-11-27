def risk_estimate(pr_win, frac_loss, frac_gain, frac):
    """
    Risk estimate using fraction of the Kelly criterion
    """
    return frac * kelly_criterion_bin(pr_win, frac_loss, frac_gain)


def kelly_criterion_bin(pr_win, frac_loss, frac_gain):
    """Binary outcomes"""
    pr_loss = 1 - pr_win
    fraction = pr_win / frac_loss - pr_loss / frac_gain

    return fraction


def optimal_bets() -> None:
    kelly_frac = 0.3

    # Random Pump fun
    frac_loss = 0.7
    pr_win = 0.1
    frac_gain = 5
    print("Random coin on Pump.Fun or similar")
    print(risk_estimate(pr_win, frac_loss, frac_gain, kelly_frac))

    # High conviction, highly liquid bets with more limited upside
    frac_loss = 0.4
    pr_win = 0.7
    frac_gain = 2
    print("High conviction, high cap")
    print(risk_estimate(pr_win, frac_loss, frac_gain, kelly_frac))

    # High conviction, highly illiquid bets with unlimited upside but lower pr
    frac_loss = 0.7
    pr_win = 0.3
    frac_gain = 5
    print("High conviction, low cap")
    print(risk_estimate(pr_win, frac_loss, frac_gain, kelly_frac))
