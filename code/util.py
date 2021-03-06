import numpy as np
import pylab as plt


def plot_with_uncertainty(x, y, ystd=None, color='r', linestyle='-', fill=True, label=''):
	
	plt.plot(x, y, color=color, linestyle=linestyle, label=label)
	
	if not ystd is None:
		lower, upper = y - np.sqrt(ystd), y + np.sqrt(ystd)
		plt.plot(x, lower, color=color, alpha=0.5, linestyle=linestyle)
		plt.plot(x, upper, color=color, alpha=0.5, linestyle=linestyle)

		if fill:
			plt.fill_between(x.ravel(), lower, upper, color=color, alpha=0.25, linestyle=linestyle)


def mult_diag(d, mtx, left=True):
    """Multiply a full matrix by a diagonal matrix.
    This function should always be faster than dot.
    Input:
      d -- 1D (N,) array (contains the diagonal elements)
      mtx -- 2D (N,N) array
    Output:
      mult_diag(d, mts, left=True) == dot(diag(d), mtx)
      mult_diag(d, mts, left=False) == dot(mtx, diag(d))
      From https://mail.scipy.org/pipermail/numpy-discussion/2007-March/026807.html
    """
    if left:
        return (d*mtx.T).T
    else:
        return d*mtx
