import logging

import numpy as np


def infer_parameters(steps=2, n_sample=50, n_samples_per_param=1, logging_level=logging.WARN):
    """Perform inference for this example.

    Parameters
    ----------
    steps : integer, optional
        Number of iterations in the sequential PMCABC algorithm ("generations"). The default value is 3
    n_samples : integer, optional
        Number of posterior samples to generate. The default value is 250.
    n_samples_per_param : integer, optional
        Number of data points in each simulated data set. The default value is 10.

    Returns
    -------
    abcpy.output.Journal
        A journal containing simulation results, metadata and optionally intermediate results.
    """
    logging.basicConfig(level=logging_level)
    # define backend
    # Note, the dummy backend does not parallelize the code!
    from abcpy.backends import BackendDummy as Backend
    backend = Backend()

    # define observation for true parameters mean=170, std=15
    height_obs = [160.82499176, 167.24266737, 185.71695756, 153.7045709, 163.40568812, 140.70658699, 169.59102084,
                  172.81041696, 187.38782738, 179.66358934, 176.63417241, 189.16082803, 181.98288443, 170.18565017,
                  183.78493886, 166.58387299, 161.9521899, 155.69213073, 156.17867343, 144.51580379, 170.29847515,
                  197.96767899, 153.36646527, 162.22710198, 158.70012047, 178.53470703, 170.77697743, 164.31392633,
                  165.88595994, 177.38083686, 146.67058471763457, 179.41946565658628, 238.02751620619537,
                  206.22458790620766, 220.89530574344568, 221.04082532837026, 142.25301427453394, 261.37656571434275,
                  171.63761180867033, 210.28121820385866, 237.29130237612236, 175.75558340169619, 224.54340549862235,
                  197.42448680731226, 165.88273684581381, 166.55094082844519, 229.54308602661584, 222.99844054358519,
                  185.30223966014586, 152.69149367593846, 206.94372818527413, 256.35498655339154, 165.43140916577741,
                  250.19273595481803, 148.87781549665536, 223.05547559193792, 230.03418198709608, 146.13611923127021,
                  138.24716809523139, 179.26755740864527, 141.21704876815426, 170.89587081800852, 222.96391329259626,
                  188.27229523693822, 202.67075179617672, 211.75963110985992, 217.45423324370509]

    # define prior
    from abcpy.continuousmodels import Uniform
    mu = Uniform([[150], [200]], name="mu")
    sigma = Uniform([[5], [25]], name="sigma")

    # define the model
    from abcpy.continuousmodels import Normal
    height = Normal([mu, sigma], )

    # 1) generate simulations from prior
    from abcpy.inferences import DrawFromPrior
    draw_from_prior = DrawFromPrior([height], backend=backend)

    # notice the use of the `.sample_par_sim_pairs` method rather than `.sample` to obtain data suitably formatted
    # for the summary statistics learning routines
    parameters, simulations = draw_from_prior.sample_par_sim_pairs(100, n_samples_per_param=1)
    # if you want to use the test loss to do early stopping in the training:
    parameters_val, simulations_val = draw_from_prior.sample_par_sim_pairs(100, n_samples_per_param=1)
    # discard the mid dimension (n_samples_per_param, as the StatisticsLearning classes use that =1)
    simulations = simulations.reshape(simulations.shape[0], simulations.shape[2])
    simulations_val = simulations_val.reshape(simulations_val.shape[0], simulations_val.shape[2])

    # 2) now train the NNs with the different methods with the generated data
    from abcpy.statistics import Identity
    identity = Identity()  # to apply before computing the statistics

    logging.info("Exponential family statistics")
    from abcpy.statisticslearning import ExponentialFamilyScoreMatching
    exp_fam_stats = ExponentialFamilyScoreMatching(
        [height], identity, backend=backend, parameters=parameters,
        simulations=simulations, parameters_val=parameters_val,
        simulations_val=simulations_val,
        early_stopping=True,  # early stopping
        seed=1, n_epochs=10, batch_size=10,
        scale_samples=False,  # whether to rescale the samples to (0,1) before NN
        scale_parameters=True,  # whether to rescale the parameters to (0,1) before NN
        embedding_dimension=3,  # embedding dimension of both simulations and parameter networks (equal to # statistics)
        sliced=True,  # quicker version of score matching
        use_tqdm=False  # do not use tqdm to display progress
    )

    # 3) save and re-load NNs:
    # get the statistics from the already fit StatisticsLearning object 'exp_fam_stats'; if rescale_statistics=True,
    # the training (or validation, if available) set is used to compute the standard deviation of the different
    # statistics, and the statistics on each new observation/simulation are then rescaled by that. This is useful as the
    # summary statistics obtained with this method can vary much in magnitude.
    learned_stat = exp_fam_stats.get_statistics(rescale_statistics=True)

    # this has a save net method:
    # if you used `scale_samples=True` in learning the NNs (or if the simulations were bounded, which is not the case
    # here), you need to provide a path where pickle stores the scaler too:
    learned_stat.save_net("exp_fam_stats.pth", path_to_scaler="scaler.pkl")

    # to reload: need to use the Neural Embedding statistics fromFile; this needs to know which kind of NN it is using;
    # need therefore to pass either the input/output size (it data size and number parameters) or the network class if
    # that was specified explicitly in the StatisticsLearning class. Check the docstring for NeuralEmbedding.fromFile
    # for more details.
    # Output size has to be here the embedding_dimension used in learning the summaries plus 1. The last component is
    # a base measure which is automatically discarded when the summary statistics are used.
    # Additionally, if you want to rescale the statistics by their standard deviation as discussed above, you need here
    # to explicitly provide the set used for estimating the standard deviation in the argument `reference_simulations`
    from abcpy.statistics import NeuralEmbedding
    learned_stat_loaded = NeuralEmbedding.fromFile("exp_fam_stats.pth", input_size=1, output_size=4,
                                                   reference_simulations=simulations_val)

    # 4) perform inference
    # define distance
    from abcpy.distances import Euclidean
    distance_calculator = Euclidean(learned_stat_loaded)

    # define kernel
    from abcpy.perturbationkernel import DefaultKernel
    kernel = DefaultKernel([mu, sigma])

    # define sampling scheme
    from abcpy.inferences import PMCABC
    sampler = PMCABC([height], [distance_calculator], backend, kernel, seed=1)

    eps_arr = np.array([500])  # starting value of epsilon; the smaller, the slower the algorithm.
    # at each iteration, take as epsilon the epsilon_percentile of the distances obtained by simulations at previous
    # iteration from the observation
    epsilon_percentile = 10
    journal = sampler.sample([height_obs], steps, eps_arr, n_sample, n_samples_per_param, epsilon_percentile)

    return journal


def analyse_journal(journal):
    # output parameters and weights
    print(journal.opt_values)
    print(journal.get_weights())

    # do post analysis
    print(journal.posterior_mean())
    print(journal.posterior_cov())

    # print configuration
    print(journal.configuration)

    # plot posterior
    journal.plot_posterior_distr(path_to_save="posterior.png")

    # save and load journal
    journal.save("experiments.jnl")

    from abcpy.output import Journal
    new_journal = Journal.fromFile('experiments.jnl')


if __name__ == "__main__":
    journal = infer_parameters(logging_level=logging.INFO)
    analyse_journal(journal)
