"""Normal and F distribution functions in pure stdlib (no scipy).

Provides normal_cdf/ppf, the regularized incomplete beta, and f_cdf/f_ppf
used for Hotelling T2 control limits. Invalid input raises DistributionError.
"""

from __future__ import annotations

import math

# Acklam (2003) rational approximation of the normal quantile, relative
# error ~1.15e-9; refined below with one Halley step to ~1e-15.
_A = (-3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02,
      1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00)
_B = (-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02,
      6.680131188771972e01, -1.328068155288572e01)
_C = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00,
      -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00)
_D = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00,
      3.754408661907416e00)
_P_LOW = 0.02425


class DistributionError(ValueError):
    """Raised when an argument lies outside the function's domain."""


def normal_cdf(x: float) -> float:
    """Standard normal CDF, accurate in both tails (via erfc)."""
    if math.isnan(x):
        raise DistributionError("x must not be NaN")
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


def _poly(coef: tuple[float, ...], q: float) -> float:
    """Evaluate a polynomial with Horner's scheme (highest degree first)."""
    acc = 0.0
    for c in coef:
        acc = acc * q + c
    return acc


def _acklam(p: float) -> float:
    """Initial normal quantile estimate for 0 < p < 1."""
    if p < _P_LOW or p > 1.0 - _P_LOW:
        q = math.sqrt(-2.0 * math.log(min(p, 1.0 - p)))
        x = _poly(_C, q) / (_poly(_D, q) * q + 1.0)
        return x if p < 0.5 else -x
    q = p - 0.5
    r = q * q
    return _poly(_A, r) * q / (_poly(_B, r) * r + 1.0)


def normal_ppf(p: float) -> float:
    """Standard normal quantile for 0 <= p <= 1 (+-inf at the ends)."""
    if not 0.0 <= p <= 1.0:
        raise DistributionError(f"p must be in [0, 1], got {p}")
    if p == 0.0:
        return -math.inf
    if p == 1.0:
        return math.inf
    x = _acklam(p)
    err = normal_cdf(x) - p
    u = err * math.sqrt(2.0 * math.pi) * math.exp(x * x / 2.0)
    return x - u / (1.0 + x * u / 2.0)


def _cf_even(m: int, x: float, a: float, b: float) -> float:
    """Even-step numerator of the incomplete beta continued fraction."""
    return m * (b - m) * x / ((a + 2.0 * m - 1.0) * (a + 2.0 * m))


def _cf_odd(m: int, x: float, a: float, b: float) -> float:
    """Odd-step numerator of the incomplete beta continued fraction."""
    return -(a + m) * (a + b + m) * x / ((a + 2.0 * m) * (a + 2.0 * m + 1.0))


def _nonzero(v: float) -> float:
    """Guard a Lentz term against exact zero."""
    return v if abs(v) > 1e-300 else 1e-300


def _beta_cf(x: float, a: float, b: float) -> float:
    """Continued fraction for the incomplete beta (modified Lentz)."""
    c = 1.0
    d = 1.0 / _nonzero(1.0 - (a + b) * x / (a + 1.0))
    h = d
    for m in range(1, 2000):
        for num in (_cf_even(m, x, a, b), _cf_odd(m, x, a, b)):
            d = 1.0 / _nonzero(1.0 + num * d)
            c = _nonzero(1.0 + num / c)
            h *= d * c
        if abs(d * c - 1.0) < 1e-15:
            return h
    raise DistributionError("incomplete beta continued fraction did not converge")


def regularized_incomplete_beta(x: float, a: float, b: float) -> float:
    """Regularized incomplete beta I_x(a, b) for 0 <= x <= 1, a, b > 0."""
    if not (a > 0.0 and b > 0.0):
        raise DistributionError(f"a and b must be > 0, got a={a}, b={b}")
    if not 0.0 <= x <= 1.0:
        raise DistributionError(f"x must be in [0, 1], got {x}")
    if x in (0.0, 1.0):
        return x
    return _ibeta_xy(x, 1.0 - x, a, b)


def _ibeta_xy(x: float, y: float, a: float, b: float) -> float:
    """I_x(a, b) given both x and y = 1 - x (keeps precision near x = 1)."""
    ln_front = (math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
                + a * math.log(x) + b * math.log(y))
    if x < (a + 1.0) / (a + b + 2.0):
        return math.exp(ln_front) * _beta_cf(x, a, b) / a
    return 1.0 - math.exp(ln_front) * _beta_cf(y, b, a) / b


def _check_dof(d1: float, d2: float) -> None:
    """Validate F degrees of freedom (finite, positive)."""
    if not (d1 > 0.0 and d2 > 0.0 and math.isfinite(d1) and math.isfinite(d2)):
        raise DistributionError(f"d1 and d2 must be finite and > 0, got {d1}, {d2}")


def f_cdf(x: float, d1: float, d2: float) -> float:
    """CDF of the F distribution with (d1, d2) degrees of freedom."""
    _check_dof(d1, d2)
    if math.isnan(x):
        raise DistributionError("x must not be NaN")
    if x <= 0.0:
        return 0.0
    if math.isinf(x):
        return 1.0
    den = d1 * x + d2
    return _ibeta_xy(d1 * x / den, d2 / den, d1 / 2.0, d2 / 2.0)


def _bracket(p: float, d1: float, d2: float) -> float:
    """Find hi with f_cdf(hi) >= p by doubling."""
    hi = 1.0
    while f_cdf(hi, d1, d2) < p:
        hi *= 2.0
        if hi > 1e300:
            raise DistributionError("could not bracket the quantile")
    return hi


def f_ppf(p: float, d1: float, d2: float) -> float:
    """Quantile of the F distribution, by bracketing and bisection."""
    _check_dof(d1, d2)
    if not 0.0 <= p <= 1.0:
        raise DistributionError(f"p must be in [0, 1], got {p}")
    if p == 0.0:
        return 0.0
    if p == 1.0:
        return math.inf
    lo, hi = 0.0, _bracket(p, d1, d2)
    for _ in range(300):
        mid = 0.5 * (lo + hi)
        if f_cdf(mid, d1, d2) < p:
            lo = mid
        else:
            hi = mid
        if hi - lo <= 1e-13 * hi:
            break
    return 0.5 * (lo + hi)
