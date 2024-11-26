def risk_estimate(pr_win, frac_loss, frac_gain, frac):
    """
    Risk estimate using frraction of the Kelly criterion
    """
    return frac * kelly_criterion_bin(pr_win, frac_loss, frac_gain)


def kelly_criterion_bin(pr_win, frac_loss, frac_gain):
    """Binary outcomes"""
    pr_loss = 1 - pr_win
    fraction = pr_win / frac_loss - pr_loss / frac_gain

    return fraction
