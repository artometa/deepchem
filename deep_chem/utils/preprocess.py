"""
Utility functions to preprocess datasets before building models.
"""
from __future__ import print_function
from __future__ import division
from __future__ import unicode_literals
import numpy as np
import warnings

__author__ = "Bharath Ramsundar"
__copyright__ = "Copyright 2015, Stanford University"
__license__ = "LGPL"


def standardize(dataset, mode):
  """Represents a loaded dataset in standardize dictionary format."""
  sorted_ids, X, task_ys, task_ws = dataset_to_numpy(dataset, mode)
  sorted_tasks = sorted(task_ys.keys())
  data = {}
  data["mol_ids"] = sorted_ids
  data["features"] = X
  data["sorted_tasks"] = sorted_tasks
  for task in sorted_tasks:
    data[task] = (task_ys[task], task_ws[task])
  return data

def dataset_to_numpy(dataset, mode):
  """Transforms a set of tensor data into standard set of numpy arrays"""
  # Perform common train/test split across all tasks
  n_samples = len(dataset.keys())
  sample_datapoint = dataset.itervalues().next()
  labels = sample_datapoint["labels"]
  sorted_tasks = sorted(labels.keys())
  n_tasks = len(sorted_tasks)
  task_ys = {task: [] for task in sorted_tasks}
  task_ws = {task: [] for task in sorted_tasks}
  sorted_ids = sorted(dataset.keys())
  tensors = []
  for mol_id in sorted_ids:
    datapoint = dataset[mol_id]
    fingerprint, labels = (datapoint["fingerprint"], datapoint["labels"])
    tensors.append(np.squeeze(fingerprint))
    # Set labels from measurements
    for task in sorted_tasks:
      if labels[task] == -1:
        task_ys[task].append(-1)
        task_ws[task].append(0)
      else:
        task_ys[task].append(labels[task])
        task_ws[task].append(1)
  X = np.stack(tensors)
  if mode == "singletask":
    for task in sorted_tasks:
      task_ys[task] = np.reshape(np.array(task_ys[task]), (n_samples, 1))
      task_ws[task] = np.reshape(np.array(task_ws[task]), (n_samples, 1))
    return sorted_ids, X, task_ys, task_ws
  elif mode == "multitask":
    y = np.zeros((n_samples, n_tasks))
    w = np.ones((n_samples, n_tasks))
    for ind, task in enumerate(sorted_tasks):
      y[:, ind] = np.array(task_ys[task])
      w[:, ind] = np.array(task_ws[task])
    return sorted_ids, X, {"all": y}, {"all": w}
  else:
    raise ValueError("Unsupported mode for process_datasets.")

def transform_inputs(X, input_transforms):
  """Transform the input feature data."""
  # Copy X up front to have non-destructive updates.
  if not input_transforms:
    return X

  X = np.copy(X)
  if len(np.shape(X)) == 2:
    n_features = np.shape(X)[1]
  else:
    raise ValueError("Only know how to transform vectorial data.")
  Z = np.zeros(np.shape(X))
  # Meant to be done after normalize
  trunc = 5
  for feature in range(n_features):
    feature_data = X[:, feature]
    for input_transform in input_transforms:
      if input_transform == "normalize-and-truncate":
        if np.amax(feature_data) > trunc or np.amin(feature_data) < -trunc:
          mean, std = np.mean(feature_data), np.std(feature_data)
          feature_data = feature_data - mean
          if std != 0.:
            feature_data = feature_data / std
          feature_data[feature_data > trunc] = trunc
          feature_data[feature_data < -trunc] = -trunc
          if np.amax(feature_data) > trunc or np.amin(feature_data) < -trunc:
            raise ValueError("Truncation failed on feature %d" % feature)
      else:
        raise ValueError("Unsupported Input Transform")
    Z[:, feature] = feature_data
  return Z

def undo_normalization(y_orig, y_pred):
  """Undo the applied normalization transform."""
  old_mean = np.mean(y_orig)
  old_std = np.std(y_orig)
  return y_pred * old_std + old_mean

def undo_transform_outputs(y_raw, y_pred, output_transforms):
  """Undo transforms on y_pred, W_pred."""
  if output_transforms == []:
    return y_pred
  elif output_transforms == ["log"]:
    return np.exp(y_pred)
  elif output_transforms == ["normalize"]:
    return undo_normalization(y_raw, y_pred)
  elif output_transforms == ["log", "normalize"]:
    return np.exp(undo_normalization(np.log(y_raw), y_pred))
  else:
    raise ValueError("Unsupported output transforms.")

def transform_outputs(y, W, output_transforms):
  """Tranform the provided outputs

  Parameters
  ----------
  y: ndarray
    Labels
  W: ndarray
    Weights
  output_transforms: list
    List of specified transforms (must be "log", "normalize"). The
    transformations are performed in the order specified. An empty list
    corresponds to no transformations. Only for regression outputs.
  """
  # Copy y up front so we have non-destructive updates
  y = np.copy(y)
  #if len(np.shape(y)) == 1:
  #  n_tasks = 1
  #elif len(np.shape(y)) == 2:
  if len(np.shape(y)) == 2:
    n_tasks = np.shape(y)[1]
  else:
    raise ValueError("y must be of shape (n_samples,n_targets)")
  for task in range(n_tasks):
    for output_transform in output_transforms:
      if output_transform == "log":
        y[:, task] = np.log(y[:, task])
      elif output_transform == "normalize":
        task_data = y[:, task]
        if task < n_tasks:
          # Only elements of y with nonzero weight in W are true labels.
          nonzero = (W[:, task] != 0)
        else:
          nonzero = np.ones(np.shape(y[:, task]), dtype=bool)
        # Set mean and std of present elements
        mean = np.mean(task_data[nonzero])
        std = np.std(task_data[nonzero])
        task_data[nonzero] = task_data[nonzero] - mean
        # Set standard deviation to one
        if std == 0.:
          print("Variance normalization skipped for task %d due to 0 stdev" % task)
          continue
        task_data[nonzero] = task_data[nonzero] / std
      else:
        raise ValueError("Unsupported Output transform")
  return y

def to_one_hot(y):
  """Transforms label vector into one-hot encoding.

  Turns y into vector of shape [n_samples, 2] (assuming binary labels).

  y: np.ndarray
    A vector of shape [n_samples, 1]
  """
  n_samples = np.shape(y)[0]
  y_hot = np.zeros((n_samples, 2))
  for index, val in enumerate(y):
    if val == 0:
      y_hot[index] = np.array([1, 0])
    elif val == 1:
      y_hot[index] = np.array([0, 1])
  return y_hot

def balance_positives(y, W):
  """Ensure that positive and negative examples have equal weight."""
  n_samples, n_targets = np.shape(y)
  for target_ind in range(n_targets):
    positive_inds, negative_inds = [], []
    to_next_target = False
    for sample_ind in range(n_samples):
      label = y[sample_ind, target_ind]
      if label == 1:
        positive_inds.append(sample_ind)
      elif label == 0:
        negative_inds.append(sample_ind)
      elif label == -1:  # Case of missing label
        continue
      else:
        warnings.warn("Labels must be 0/1 or -1 " +
                      "(missing data) for balance_positives target %d. " % target_ind +
                      "Continuing without balancing.")
        to_next_target = True
        break
    if to_next_target:
      continue
    n_positives, n_negatives = len(positive_inds), len(negative_inds)
    # TODO(rbharath): This results since the coarse train/test split doesn't
    # guarantee that the test set actually has any positives for targets. FIX
    # THIS BEFORE RELEASE!
    if n_positives == 0:
      pos_weight = 0
    else:
      pos_weight = float(n_negatives)/float(n_positives)
    W[positive_inds, target_ind] = pos_weight
    W[negative_inds, target_ind] = 1
  return W

def multitask_to_singletask(dataset):
  """Transforms a multitask dataset to a singletask dataset.

  Returns a dictionary which maps target names to datasets, where each
  dataset is itself a dict that maps identifiers to
  (fingerprint, scaffold, dict) tuples.

  Parameters
  ----------
  dataset: dict
    Dictionary of type produced by load_datasets
  """
  # Generate single-task data structures
  labels = dataset.itervalues().next()["labels"]
  sorted_targets = sorted(labels.keys())
  singletask_features = []
  singletask_labels = {target: [] for target in sorted_targets}
  # Populate the singletask datastructures
  sorted_ids = sorted(dataset.keys())
  for mol_id in sorted_ids:
    datapoint = dataset[mol_id]
    labels = datapoint["labels"]
    singletask_features.append(datapoint["fingeprint"])
    for target in sorted_targets:
      if labels[target] == -1:
        continue
      else:
        singletask_labels[target].append(labels[target])
  return singletask_features, singletask_labels

def split_dataset(dataset, splittype, seed=None):
  """Split provided data using specified method."""
  if splittype == "random":
    train, test = train_test_random_split(dataset, seed=seed)
  elif splittype == "scaffold":
    train, test = train_test_scaffold_split(dataset)
  elif splittype == "specified":
    train, test = train_test_specified_split(dataset)
  else:
    raise ValueError("Improper splittype.")
  return train, test

def train_test_specified_split(dataset):
  """Split provided data due to splits in origin data."""
  train, test = {}, {}
  for mol_id, datapoint in dataset.iteritems():
    if "split" not in datapoint:
      raise ValueError("Missing required split information.")
    if datapoint["split"].lower() == "train":
      train[mol_id] = datapoint
    elif datapoint["split"].lower() == "test":
      test[mol_id] = datapoint
  return train, test

def train_test_random_split(dataset, frac_train=.8, seed=None):
  """Splits provided data into train/test splits randomly.

  Performs a random 80/20 split of the data into train/test. Returns two
  dictionaries

  Parameters
  ----------
  dataset: dict
    A dictionary of type produced by load_datasets.
  frac_train: float
    Proportion of data in train set.
  seed: int (optional)
    Seed to initialize np.random.
  """
  np.random.seed(seed)
  shuffled = np.random.permutation(dataset.keys())
  train_cutoff = np.floor(frac_train * len(shuffled))
  train_keys, test_keys = shuffled[:train_cutoff], shuffled[train_cutoff:]
  train, test = {}, {}
  for key in train_keys:
    train[key] = dataset[key]
  for key in test_keys:
    test[key] = dataset[key]
  return train, test

def train_test_scaffold_split(dataset, frac_train=.8):
  """Splits provided data into train/test splits by scaffold.

  Groups the largest scaffolds into the train set until the size of the
  train set equals frac_train * len(dataset). Adds remaining scaffolds
  to test set. The idea is that the test set contains outlier scaffolds,
  and thus serves as a hard test of generalization capability for the
  model.

  Parameters
  ----------
  dataset: dict
    A dictionary of type produced by load_datasets.
  frac_train: float
    The fraction (between 0 and 1) of the data to use for train set.
  """
  scaffolds = scaffold_separate(dataset)
  train_size = frac_train * len(dataset)
  train, test = {}, {}
  for elements in scaffolds:
    # If adding this scaffold makes the train_set too big, add to test set.
    if len(train) + len(elements) > train_size:
      for elt in elements:
        test[elt] = dataset[elt]
    else:
      for elt in elements:
        train[elt] = dataset[elt]
  return train, test

def scaffold_separate(dataset):
  """Splits provided data by compound scaffolds.

  Returns a list of pairs (scaffold, [identifiers]), where each pair
  contains a scaffold and a list of all identifiers for compounds that
  share that scaffold. The list will be sorted in decreasing order of
  number of compounds.

  Parameters
  ----------
  dataset: dict
    A dictionary of type produced by load_datasets.
  """
  scaffolds = {}
  for mol_id in dataset:
    datapoint = dataset[mol_id]
    scaffold = datapoint["scaffold"]
    if scaffold not in scaffolds:
      scaffolds[scaffold] = [mol_id]
    else:
      scaffolds[scaffold].append(mol_id)
  # Sort from largest to smallest scaffold sets
  return [elt for (scaffold, elt) in sorted(scaffolds.items(), key=lambda x: -len(x[1]))]