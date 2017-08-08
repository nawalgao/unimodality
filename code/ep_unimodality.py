import numpy as np

from scipy.integrate import quad, dblquad
from scipy.stats import norm

from probit_moments import ProbitMoments
from moment_functions import compute_moments_softinformation, compute_moments_strict

npdf = lambda x, m, v: 1./np.sqrt(2*np.pi*v)*np.exp(-(x-m)**2/(2*v))
log_npdf = lambda x, m, v: -0.5*np.log(2*np.pi*v) -(x-m)**2/(2*v)
phi = lambda x: norm.cdf(x)
logphi = lambda x: norm.logcdf(x)


def generate_joint_derivative_kernel(t, t2, k1, k2, jitter = 1e-8):

    assert(t.ndim == 2), "Wrong dimensions for t"
    assert(t2.ndim == 2), "Wrong dimensions for t"

    # kernel functions
    cov_fun, cov_fun1, cov_fun2 = lambda x, y: k1**2*np.exp(-0.5*(x-y)**2/k2**2), lambda x, y: -cov_fun(x,y)*(x-y)/k2**2, lambda x, y: cov_fun(x,y)*(1 - (x-y)**2/k2**2 )/k2**2

    # Prepare for joint kernel
    N, M = t.shape[0], t2.shape[0]
    K = np.zeros((N + M, N + M))

    # Kernel for regular observations and derivative observations
    K[:N, :N] = cov_fun(t, t.T)
    K[N:, N:] = cov_fun2(t2, t2.T)

    # Kernel for covariance between reg. and der. observations
    K[N:, :N] = cov_fun1(t2, t.T)
    K[:N, N:] = K[N:, :N].T

    # jitter
    K += jitter*np.identity(N + M)

    return K

def update_posterior(K, eta, theta):
    D = K.shape[0]
    sqrt_theta = np.sqrt(theta)
    G = sqrt_theta[:, None]*K
    B = np.identity(D) + G*sqrt_theta
    L = np.linalg.cholesky(B)
    V = np.linalg.solve(L, G)
    Sigma_full = K - np.dot(V.T, V)
    mu, Sigma = np.dot(Sigma_full, eta), np.diag(Sigma_full)

    return mu, Sigma, Sigma_full, L


def ep_unimodality(t, y, k1, k2, sigma2, t2=None, m=None, max_itt=50, nu=10., nu2 = 1., alpha=0.9, tol=1e-4, verbose=0, c1=None, c2=None, moment_function=None, seed=0):

	np.random.seed(seed)

	if t2 is None:
		t2 = t.copy()

	N, M = len(t), len(t2)
	Df = N + M
	Dg = M + M

	if m is None:
		m = np.ones(M)

	# Hyperparameter for g
	if c1 is None:
		c1 = k1
	if c2 is None:
		c2 = k2

	# moment function
	if moment_function is None:
		moment_function = compute_moments_strict



	# sites for likelihood 
	eta_y, theta_y = np.zeros(Df), np.zeros(Df)
	eta_y[:N], theta_y[:N] = y[:, 0]/sigma2, 1./sigma2

	# sites connecting f' and g
	eta_fp, theta_fp = np.zeros(Df), 1e-10*np.ones(Df)
	eta_g, theta_g = np.zeros(Dg), 1e-10*np.ones(Dg)

	# sites for g' and m
	eta_gp, theta_gp = np.zeros(Dg), 1e-10*np.ones(Dg)

	# prepare kernels
	Kf = generate_joint_derivative_kernel(t, t2, k1, k2)
	Kg = generate_joint_derivative_kernel(t2, t2, c1, c2)

	# prepare global approximation
	mu_f, Sigma_f, Sigma_full_f, Lf = update_posterior(Kf, eta_fp + eta_y, theta_fp + theta_y)
	mu_g, Sigma_g, Sigma_full_g, Lg = update_posterior(Kg, eta_gp, theta_gp)

	for itt in range(max_itt):

		old_params = np.hstack((mu_f, Sigma_f, mu_g, Sigma_g))

		if verbose > 0:
			print('Iteration %d' % (itt + 1))

		# approximate constraints to enforce monotonicity to g
		j_list = np.random.choice(range(M), size=M, replace=False) if M > 0 else []
		for j in j_list:

			# compute offset for gradient indices
			i = M + j

			# compute cavity
			eta_cav, theta_cav = mu_g[i]/Sigma_g[i] - eta_gp[j], 1./Sigma_g[i] - theta_gp[j]
			m_cav, v_cav = eta_cav/theta_cav, 1./theta_cav

			if v_cav <= 0:
				print('EP: Negative cavity observed at site %d in iteration %d, skipping update' % (j, itt + 1))
				continue

			# Compute moments
			#tilted = lambda x: phi(m[j]*nu*x)*npdf(x, m_cav, v_cav)
			#lower, upper = m_cav - 6*np.sqrt(v_cav), m_cav + 6*np.sqrt(v_cav)
			#Z = quad(tilted, lower, upper)[0]

			#site_m = quad(lambda x: x*tilted(x), lower, upper)[0]/Z
			#site_m2 = quad(lambda x: x**2*tilted(x), lower, upper)[0]/Z

			s = m[j]
			mean, variance = s*nu*m_cav, (s*nu)**2*v_cav
			z = mean/np.sqrt(1 + variance)

			# Normalization            
			Z = phi(z)

			# First moment
			qs = Z*m_cav + s*nu*v_cav*npdf(z, 0, 1)/np.sqrt(1 + variance)
			site_m = qs/Z

			# Second moment
			d, b = s*nu*v_cav*npdf(z, 0, 1)/(Z*np.sqrt(1 + variance)), (s*nu)**2*v_cav**2*z*npdf(z, 0, 1)/(Z*(1 + variance))
			q2s = Z*(2*m_cav*(m_cav + d) + v_cav - m_cav**2 - b)
			site_m2 = q2s/Z

			# variance
			site_v = site_m2 - site_m**2

			new_eta = site_m/site_v - eta_cav
			new_theta = 1./site_v - theta_cav

			if new_theta < 0:
				new_theta = 1e-10
				new_variance = 1./(new_theta + theta_cav)
				new_eta = site_m/new_variance - eta_cav

			# update site
			eta_gp[i], theta_gp[i] = (1-alpha)*eta_gp[i] + alpha*new_eta, (1-alpha)*theta_gp[i] + alpha*new_theta

			# update joint
			mu_g, Sigma_g, Sigma_full_g, Lg = update_posterior(Kg, eta_g + eta_gp, theta_g + theta_gp)


		# approximate constraints to enforce a single sign change for f'
		j_list = np.random.choice(range(M), size=M, replace=False) if M > 0 else []
		for j in j_list:

			i = N + j

			# compute cavity
			eta_cav_fp, theta_cav_fp = mu_f[i]/Sigma_f[i] - eta_fp[j], 1./Sigma_f[i] - theta_fp[j]
			eta_cav_g, theta_cav_g = mu_g[j]/Sigma_g[j] - eta_g[j], 1./Sigma_g[j] - theta_g[j]

			# transform to means and variances
			m_cav_fp, v_cav_fp = eta_cav_fp/theta_cav_fp, 1./theta_cav_fp
			m_cav_g, v_cav_g = eta_cav_g/theta_cav_g, 1./theta_cav_g

			if v_cav_fp <= 0 or v_cav_g <= 0:
				print('Negative cavity variance for site %d! Skipping...' % j)
				continue

			# compute moments
			# Z_fp, m1_fp, m2_fp = ProbitMoments.compute_moments(m=0, v=1, mu=m_cav_fp, sigma2=v_cav_fp, return_normalizer=True, normalized=False)
			# Z_g, m1_g, m2_g = ProbitMoments.compute_moments(m=0, v=1, mu=m_cav_g, sigma2=v_cav_g, return_normalizer=True, normalized=False)
			# Z = (1-Z_fp)*(1-Z_g) + Z_fp*Z_g

			# site_fp_m = ((m_cav_fp-m1_fp)*(1-Z_g) + m1_fp*Z_g)/Z
			# site_fp_m2 = (((m_cav_fp**2 + v_cav_fp)-m2_fp)*(1-Z_g) + m2_fp*Z_g)/Z
			# site_g_m = ((1-Z_fp)*(m_cav_g-m1_g) + Z_fp*m1_g)/Z
			# site_g_m2 = ((1-Z_fp)*((m_cav_g**2 + v_cav_g)-m2_g) + m2_g*Z_fp)/Z

			Z, site_fp_m, site_fp_m2, site_g_m, site_g_m2 = moment_function(m_cav_fp, v_cav_fp, m_cav_g, v_cav_g, nu2=nu2)

			if Z == 0 or np.isnan(Z):
				print('Z = 0 occured, skipping...')
				continue

			# variances
			site_fp_v = site_fp_m2 - site_fp_m**2
			site_g_v = site_g_m2 - site_g_m**2

			# new sites
			new_eta_fp, new_theta_fp = site_fp_m/site_fp_v - eta_cav_fp, 1./site_fp_v - theta_cav_fp
			new_eta_g, new_theta_g = site_g_m/site_g_v - eta_cav_g, 1./site_g_v - theta_cav_g

			if new_theta_fp <= 0:
				new_theta_fp = 1e-6
				new_variance_fp = 1./(new_theta_fp + theta_cav_fp)
				new_eta_fp = site_fp_m/new_variance_fp - eta_cav_fp

			if new_theta_g <= 0:
				new_theta_g = 1e-6
				new_variance_g = 1./(new_theta_g + theta_cav_g)
				new_eta_g = site_g_m/new_variance_g - eta_cav_g


			# update site
			eta_fp[i] = (1-alpha)*eta_fp[i] + alpha*new_eta_fp
			theta_fp[i] = (1-alpha)*theta_fp[i] + alpha*new_theta_fp

			eta_g[j] = (1-alpha)*eta_g[j] + alpha*new_eta_g
			theta_g[j] = (1-alpha)*theta_g[j] + alpha*new_theta_g

			# update posterior
			mu_f, Sigma_f, Sigma_full_f, Lf = update_posterior(Kf, eta_fp + eta_y, theta_fp + theta_y)
			mu_g, Sigma_g, Sigma_full_g, Lg = update_posterior(Kg, eta_g + eta_gp, theta_g + theta_gp)

		# check for convergence
		new_params = np.hstack((mu_f, Sigma_f, mu_g, Sigma_g))
		if len(old_params) > 0 and np.mean((new_params-old_params)**2)/np.mean(old_params**2) < tol:
			print('Converged in %d iterations' % (itt + 1))
			break



	# marginal likelihood
	f_term = compute_marginal_likelihood_mvn(Lf, mu_f, Sigma_full_f, eta_fp + eta_y, theta_fp + theta_y)
	g_term = compute_marginal_likelihood_mvn(Lg, mu_g, Sigma_full_g, eta_g + eta_gp, theta_g + theta_gp)

	# log k_i
	eta_cav, theta_cav = mu_g/Sigma_g - eta_gp, 1./Sigma_g - theta_gp
	mu_cav, tau_cav = eta_cav/theta_cav, 1./theta_cav

	log_k1 = np.sum(logphi(m.ravel()*mu_cav[M:]/np.sqrt(1 + tau_cav[M:])))
	log_k2 = 0.5*np.sum(np.log(tau_cav[M:] + 1./theta_gp[M:])) + 0.5*np.sum((mu_cav[M:] - eta_gp[M:]/theta_gp[M:])**2/(tau_cav[M:] + 1./theta_gp[M:]))


	# log c_i
	eta_cav_fp, theta_cav_fp = mu_f/Sigma_f - eta_fp, 1./Sigma_f - theta_fp
	eta_cav_g, theta_cav_g = mu_g/Sigma_g - eta_g, 1./Sigma_g - theta_g

	m_cav_fp, v_cav_fp = eta_cav_fp/theta_cav_fp, 1./theta_cav_fp
	m_cav_g, v_cav_g = eta_cav_g/theta_cav_g, 1./theta_cav_g

	log_c1 = np.sum(ProbitMoments.compute_normalization(m=0, v=-1./nu2, mu=m_cav_fp[N:], sigma2=v_cav_fp[N:], log=True)) + np.sum(ProbitMoments.compute_normalization(m=0, v=1./nu2, mu=m_cav_fp[N:], sigma2=v_cav_fp[N:], log=True))
	log_c2 = np.sum(logphi(-m_cav_g[:M]/np.sqrt(1 + v_cav_g[:M]))) + np.sum(logphi(m_cav_g[:M]/np.sqrt(1 + v_cav_g[:M])))

	log_c3 = 0.5*np.sum(np.log(v_cav_fp[N:] + 1./theta_fp[N:])) + 0.5*np.sum((m_cav_fp[N:] - eta_fp[N:]/theta_fp[N:])**2/(v_cav_fp[N:] + 1./theta_fp[N:]))
	log_c4 = 0.5*np.sum(np.log(v_cav_g[:M] + 1./theta_g[:M])) + 0.5*np.sum((m_cav_g[:M] - eta_g[:M]/theta_g[:M])**2/(v_cav_g[:M] + 1./theta_g[:M]))

	logZ = log_k1 + log_k2 + log_c1 + log_c2 + log_c3 + log_c4 +  f_term + g_term

	# import pdb
	# pdb.set_trace()
	
	return mu_f, Sigma_f, Sigma_full_f, mu_g, Sigma_g, Sigma_full_g, logZ

def compute_marginal_likelihood_mvn(L, mu, Sigma, eta, theta):
    
    # eta_cav, theta_cav = mu/Sigma - eta_z, 1./Sigma - theta_z
    # m_cav, v_cav = eta_cav/theta_cav, 1./theta_cav
    b = np.linalg.solve(L, eta/np.sqrt(theta))

    # log_s1 = np.sum(logphi(z.ravel()*m_cav[N:]/np.sqrt(1 + v_cav[N:])))
    # log_s2 = 0.5*np.sum(np.log(v_cav[N:] + 1./theta_z[N:])) + 0.5*np.sum((m_cav[N:] - eta_z[N:]/theta_z[N:])**2/(v_cav[N:] + 1./theta_z[N:]))

    logdet = np.sum(np.log(np.diag(L))) - np.sum(np.log(np.sqrt(theta)))
    quadterm = 0.5*np.sum(b**2)

    return -0.5*len(mu)*np.log(2*np.pi)  - logdet - quadterm


def _predict(mu, Sigma_full, t, t2, t_pred, k1, k2):
	""" returns predictive mean and full covariance """
	# kernel functions
	cov_fun = lambda x, y: k1**2*np.exp(-0.5*(x-y)**2/k2**2)
	cov_fun1 = lambda x, y: -cov_fun(x,y)*(x-y)/k2**2
	cov_fun2 = lambda x, y: cov_fun(x,y)*(1 - (x-y)**2/k2**2 )/k2**2

	D, N, P = len(mu), t.shape[0], t_pred.shape[0]

	K = generate_joint_derivative_kernel(t, t2, k1, k2)

	Kpp = cov_fun(t_pred, t_pred.T)
	Kpf = np.zeros((P, D))
	Kpf[:, :N] = cov_fun(t_pred, t.T)
	Kpf[:, N:] = cov_fun1(t2, t_pred.T).T

	H =  np.linalg.solve(K, Kpf.T)
	pred_mean = np.dot(H.T, mu)
	pred_cov = Kpp -  np.dot(Kpf, H) + np.dot(H.T, np.dot(Sigma_full, H))
	return pred_mean, pred_cov

def predict(mu, Sigma_full, t, t2, t_pred, k1, k2, sigma2 = None):

	pred_mean, pred_cov = _predict(mu, Sigma_full, t, t2, t_pred, k1, k2)
	pred_var_ = np.diag(pred_cov)

	if sigma2 is None:
		sigma2 = 0

	pred_var = pred_var_ + sigma2

	return pred_mean, pred_var

def lppd(ytest, mu, Sigma_full, t, t2, t_pred, k1, k2, sigma2 = None, per_sample=False):
	pred_mean, pred_var = predict(mu, Sigma_full, t, t2, t_pred, k1, k2, sigma2)

	lppd = log_npdf(ytest.ravel(), pred_mean, pred_var)

	if not per_sample:
		lppd = np.sum(lppd)

	return lppd





def sample_z_probabilities(mu, Sigma_full, t, t2, t_pred, k1, k2, num_samples = 1000):


	pred_mean, pred_cov = _predict(mu, Sigma_full, t, t2, t_pred, k1, k2)
	D = pred_cov.shape[0]

	L = np.linalg.cholesky(pred_cov + 1e-8*np.identity(D)) 

	zs = pred_mean[:, None] + np.dot(L, np.random.normal(0, 1, size=(D, num_samples)))
	pzs = phi(zs)

	return np.mean(pzs, axis = 1), np.var(pzs, axis = 1)