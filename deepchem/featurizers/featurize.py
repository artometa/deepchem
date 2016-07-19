"""
Process an input dataset into a format suitable for machine learning.
"""
from __future__ import print_function
from __future__ import division
from __future__ import unicode_literals
import os
import gzip
import pandas as pd
import numpy as np
import csv
import numbers
import dill
import itertools
import multiprocessing as mp
from functools import partial
from rdkit import Chem
import itertools as it
import traceback
from multiprocessing.pool import Pool
from deepchem.utils.save import log
from deepchem.utils.save import save_to_disk
from deepchem.utils.save import load_pickle_from_disk
from deepchem.featurizers import Featurizer, ComplexFeaturizer
from deepchem.featurizers import UserDefinedFeaturizer
from deepchem.datasets import Dataset
from deepchem.utils.save import load_data
from deepchem.utils.save import get_input_type
############################################################## DEBUG
import time
import sys
############################################################## DEBUG

#def _process_helper(row, loader, fields, input_type):
#  return loader._process_raw_sample(input_type, row, fields)


# Shortcut to multiprocessing's logger
# http://stackoverflow.com/questions/6728236/exception-thrown-in-multiprocessing-pool-not-detected
def error(msg, *args):
  ############################################################# DEBUG
  import sys
  sys.stdout.flush()
  ############################################################# DEBUG
  return mp.get_logger().error(msg, *args)

class LogExceptions(object):
  def __init__(self, callable):
    self.__callable = callable

  def __call__(self, *args, **kwargs):
    try:
        result = self.__callable(*args, **kwargs)

    except Exception as e:
        # Here we add some debugging help. If multiprocessing's
        # debugging is on, it will arrange to log the traceback
        error(traceback.format_exc())
        # Re-raise the original exception so the Pool worker can
        # clean up
        raise

    # It was fine, give a normal answer
    return result

class LoggingPool(Pool):
  def apply_async(self, func, args=(), kwds={}, callback=None):
    return Pool.apply_async(self, LogExceptions(func), args, kwds, callback)

  def map_async(self, func, iterable, chunksize=None, callback=None):
    return Pool.map_async(self, LogExceptions(func), iterable, chunksize, callback)

def featurize_map_function(args):
  #try:
  ############################################################## DEBUG
  time1 = time.time()
  ############################################################## DEBUG
  ((loader, shard_size, input_type, data_dir), (shard_num, raw_df_shard)) = args
  log("Loading shard %d of size %s from file." % (shard_num+1, str(shard_size)),
      loader.verbosity)
  log("About to featurize shard.", loader.verbosity)
  write_fn = partial(
      Dataset.write_dataframe, data_dir=data_dir,
      featurizer=loader.featurizer, tasks=loader.tasks,
      mol_id_field=loader.id_field)
  #process_fn = partial(_process_helper, loader=loader,
  #                     fields=raw_df_shard.keys(),
  #                     input_type=input_type)
  ############################################################## DEBUG
  shard_time1 = time.time()
  ############################################################## DEBUG
  metadata_row = loader._featurize_shard(
  #    raw_df_shard, process_fn, write_fn, shard_num, input_type)
  ############################################################## DEBUG
      raw_df_shard, write_fn, shard_num, input_type)
  ############################################################## DEBUG
  shard_time2 = time.time()
  print("SHARD FEATURIZATION TOOK %0.3f s" % (shard_time2-shard_time1))
  ############################################################## DEBUG
  log("Sucessfully featurized shard %d" % shard_num, loader.verbosity)
  ############################################################## DEBUG
  time2 = time.time()
  print("FEATURIZATION MAP FUNCTION TOOK %0.3f s" % (time2-time1))
  ############################################################## DEBUG
  return metadata_row
  #except:
  #  print("Shard %d featurization crashed!" % shard_num)
  #  return None


#def _process_field(val):
#  """Parse data in a field."""
#  if (isinstance(val, numbers.Number) or isinstance(val, np.ndarray)):
#    return val
#  elif isinstance(val, list):
#    return [_process_field(elt) for elt in val]
#  elif isinstance(val, str):
#    try:
#      return float(val)
#    except ValueError:
#      return val
#  elif isinstance(val, Chem.Mol):
#    return val
#  else:
#    raise ValueError("Field of unrecognized type: %s" % str(val))

class DataFeaturizer(object):
  """
  Handles loading/featurizing of chemical samples (datapoints).

  Currently knows how to load csv-files/pandas-dataframes/SDF-files. Writes a
  dataframe object to disk as output.
  """

  def __init__(self, tasks, smiles_field=None,
               id_field=None, threshold=None,
               mol_field=None, featurizer=None,
               verbosity=None, log_every_n=1000):
    """Extracts data from input as Pandas data frame"""
    if not isinstance(tasks, list):
      raise ValueError("tasks must be a list.")
    assert verbosity in [None, "low", "high"]
    self.verbosity = verbosity
    self.tasks = tasks
    self.smiles_field = smiles_field
    if id_field is None:
      self.id_field = smiles_field
    else:
      self.id_field = id_field
    self.threshold = threshold
    self.mol_field = mol_field
    self.user_specified_features = None
    if isinstance(featurizer, UserDefinedFeaturizer):
      self.user_specified_features = featurizer.feature_fields 
    self.featurizer = featurizer
    self.log_every_n = log_every_n

  def featurize(self, input_files, data_dir, shard_size=8192,
                num_shards_per_batch=24, worker_pool=None,
                logging=True, debug=False):
    """Featurize provided files and write to specified location."""
    ############################################################## DEBUG
    time1 = time.time()
    ############################################################## DEBUG
    log("Loading raw samples now.", self.verbosity)
    log("shard_size: %d" % shard_size, self.verbosity)
    log("num_shards_per_batch: %d" % num_shards_per_batch, self.verbosity)

    # Allow users to specify a single file for featurization
    if not isinstance(input_files, list):
      input_files = [input_files]

    if not os.path.exists(data_dir):
      os.makedirs(data_dir)

    # Construct partial function to write datasets.
    if not len(input_files):
      return None
    input_type = get_input_type(input_files[0])

    if logging:
      mp.log_to_stderr()
    if worker_pool is None:
      ############################################################## DEBUG
      if logging:
        worker_pool = LoggingPool(processes=1)
      else:
        worker_pool = mp.Pool(processes=1)
      ############################################################## DEBUG
    log("Spawning workers now.", self.verbosity)
    metadata_rows = []
    data_iterator = it.izip(
        it.repeat((self, shard_size, input_type, data_dir)),
        enumerate(load_data(input_files, shard_size, self.verbosity)))
    ###### Turns out python map is terrible and exhausts the
    ###### generator as given. Solution seems to be to to manually pull out N elements
    ###### from iterator, then to map on only those N elements. BLECH. Python
    ###### should do a better job here.
    num_batches = 0
    ############################################################## DEBUG
    time2 = time.time()
    print("PRE MAP FEATURIZATION TOOK %0.3f s" % (time2-time1))
    ############################################################## DEBUG
    while True:
      log("About to start processing next batch of shards", self.verbosity)
      ############################################################## DEBUG
      time1 = time.time()
      ############################################################## DEBUG
      iterator = itertools.islice(data_iterator, num_shards_per_batch)
      if not debug:
        batch_metadata = worker_pool.map(
            featurize_map_function, iterator)
      else:
        batch_metadata = []
        for elt in iterator:
          batch_metadata.append(featurize_map_function(elt))
      ############################################################## DEBUG
      time2 = time.time()
      print("MAP CALL TOOK %0.3f s" % (time2-time1))
      ############################################################## DEBUG
      if batch_metadata:
        metadata_rows.extend([elt for elt in batch_metadata if elt is not None])
        num_batches += 1
        log("Featurized %d datapoints\n"
            % (shard_size * num_shards_per_batch * num_batches), self.verbosity)
      else:
        break
    ############################################################## DEBUG
    time1 = time.time()
    ############################################################## DEBUG

    # TODO(rbharath): This whole bit with metadata_rows is an awkward way of
    # creating a Dataset. Is there a more elegant solutions?
    dataset = Dataset(data_dir=data_dir,
                      metadata_rows=metadata_rows,
                      reload=reload, verbosity=self.verbosity)
    ############################################################## DEBUG
    time2 = time.time()
    print("POST MAP DATASET CONSTRUCTION TOOK %0.3f s" % (time2-time1))
    ############################################################## DEBUG
    return dataset 

  #def _featurize_shard(self, raw_df_shard, process_fn, write_fn, shard_num,
  #                     input_type):
  ############################################################## DEBUG
  def _featurize_shard(self, raw_df_shard, write_fn, shard_num, input_type):
  ############################################################## DEBUG
    """Featurizes a shard of an input dataframe."""
    ############################################################## DEBUG
    time1 = time.time()
    ############################################################## DEBUG
    log("Applying processing transformation to shard.",
        self.verbosity)
    #raw_df_shard = raw_df_shard.apply(
    #    process_fn, axis=1, reduce=False)
    ############################################################## DEBUG
    time2 = time.time()
    print("PROCESSING TRANSFORMATION TOOK %0.3f s" % (time2-time1))
    ############################################################## DEBUG
    ############################################################## DEBUG
    time1 = time.time()
    ############################################################## DEBUG
    log("About to standardize dataframe.")
    #df_shard = self._standardize_df(raw_df_shard) 
    df_shard = raw_df_shard
    ############################################################## DEBUG
    time2 = time.time()
    print("STANDARDIZATION TOOK %0.3f s" % (time2-time1))
    ############################################################## DEBUG
  
    field = self.mol_field if input_type == "sdf" else self.smiles_field 
    log("Currently featurizing feature_type: %s"
        % self.featurizer.__class__.__name__, self.verbosity)
    if isinstance(self.featurizer, UserDefinedFeaturizer):
      self._add_user_specified_features(df_shard, self.featurizer)
    elif isinstance(self.featurizer, Featurizer):
      self._featurize_mol(df_shard, self.featurizer, field=field)
    elif isinstance(self.featurizer, ComplexFeaturizer):
      self._featurize_complexes(df_shard, self.featurizer)
    basename = "shard-%d" % shard_num 
    ############################################################## DEBUG
    time1 = time.time()
    ############################################################## DEBUG
    ############################################################## DEBUG
    print("About to invoke write_fn")
    ############################################################## DEBUG
    metadata_row = write_fn((basename, df_shard))
    ############################################################## DEBUG
    time2 = time.time()
    print("WRITING METADATA ROW TOOK %0.3f s" % (time2-time1))
    ############################################################## DEBUG
    return metadata_row

  def _shard_files_exist(self, feature_dir):
    """Checks if data shard files already exist."""
    for filename in os.listdir(feature_dir):
      if "features_shard" in filename:
        return True
    return False

  #def _process_raw_sample(self, input_type, row, fields):
  #  """Extract information from row data."""
  #  data = {}
  #  if input_type == "csv":
  #    for ind, field in enumerate(fields):
  #      data[field] = _process_field(row[ind])
  #  elif input_type in ["pandas-pickle", "pandas-joblib", "sdf"]:
  #    for field in fields:
  #      data[field] = _process_field(row[field])
  #  else:
  #    raise ValueError("Unrecognized input_type")
  #  if self.threshold is not None:
  #    for task in self.tasks:
  #      raw = _process_field(data[task])
  #      if not isinstance(raw, float):
  #        raise ValueError("Cannot threshold non-float fields.")
  #      data[field] = 1 if raw > self.threshold else 0
  #  return data

  #def _standardize_df(self, ori_df):
  #  """Copy specified columns to new df with standard column names.

  #  TODO(rbharath): I think think function is now unnecessary (since the
  #                  dataframes are only temporary and not on disk). Should
  #                  be able to remove this function.
  #  """
  #  df = pd.DataFrame(ori_df[[self.id_field]])
  #  df.columns = ["mol_id"]
  #  if self.smiles_field is not None:
  #    df["smiles"] = ori_df[[self.smiles_field]]
  #  for task in self.tasks:
  #    df[task] = ori_df[[task]]
  #  if self.user_specified_features is not None:
  #    for feature in self.user_specified_features:
  #      df[feature] = ori_df[[feature]]
  #  if self.mol_field is not None:
  #    df["mol"] = ori_df[[self.mol_field]]
  #  return df

  def _featurize_complexes(self, df, featurizer, parallel=True,
                           worker_pool=None):
    """Generates circular fingerprints for dataset."""
    protein_pdbs = list(df["protein_pdb"])
    ligand_pdbs = list(df["ligand_pdb"])
    complexes = zip(ligand_pdbs, protein_pdbs)

    def featurize_wrapper(ligand_protein_pdb_tuple):
      ligand_pdb, protein_pdb = ligand_protein_pdb_tuple
      print("Featurizing %s" % ligand_pdb[0:2])
      molecule_features = featurizer.featurize_complexes(
          [ligand_pdb], [protein_pdb], verbosity=self.verbosity)
      return molecule_features

    if worker_pool is None:
      features = []
      for ligand_protein_pdb_tuple in zip(ligand_pdbs, protein_pdbs):
        features.append(featurize_wrapper(ligand_protein_pdb_tuple))
    else:
      features = worker_pool.map_sync(featurize_wrapper, 
                                      zip(ligand_pdbs, protein_pdbs))
      #features = featurize_wrapper(zip(ligand_pdbs, protein_pdbs))
    df[featurizer.__class__.__name__] = list(features)

  def _featurize_mol(self, df, featurizer, parallel=True, field="mol",
                     worker_pool=None):    
    """Featurize individual compounds.

       Given a featurizer that operates on individual chemical compounds 
       or macromolecules, compute & add features for that compound to the 
       features dataframe

       When featurizing a .sdf file, the 3-D structure should be preserved
       so we use the rdkit "mol" object created from .sdf instead of smiles
       string. Some featurizers such as CoulombMatrix also require a 3-D
       structure.  Featurizing from .sdf is currently the only way to
       perform CM feautization.

      TODO(rbharath): Needs to be merged with _featurize_compounds
    """
    assert field in ["mol", "smiles"]
    #sample_mols = df["mol"].tolist()
    sample_elems = df[field].tolist()

    if worker_pool is None:
      features = []
      for ind, elem in enumerate(sample_elems):
        if field == "smiles":
          mol = Chem.MolFromSmiles(elem)
        else:
          mol = elem
        if ind % self.log_every_n == 0:
          log("Featurizing sample %d" % ind, self.verbosity)
        features.append(featurizer.featurize([mol], verbosity=self.verbosity))
    else:
      def featurize_wrapper(elem, dilled_featurizer):
        print("Featurizing %s" % elem)
        if field == "smiles":
          mol = Chem.MolFromSmiles(smiles)
        else:
          mol = elem
        featurizer = dill.loads(dilled_featurizer)
        feature = featurizer.featurize([mol], verbosity=self.verbosity)
        return feature

      features = worker_pool.map_sync(featurize_wrapper, 
                                      sample_elems)

    df[featurizer.__class__.__name__] = features

  def _add_user_specified_features(self, df, featurizer):
    """Merge user specified features. 

      Merge features included in dataset provided by user
      into final features dataframe

      Three types of featurization here:

        1) Molecule featurization
          -) Smiles string featurization
          -) Rdkit MOL featurization
        2) Complex featurization
          -) PDB files for interacting molecules.
        3) User specified featurizations.
    """
    ############################################################## DEBUG
    time1 = time.time()
    ############################################################## DEBUG
    log("Aggregating User-Specified Features", self.verbosity)
    features_data = []
    ############################################################## DEBUG
    df[featurizer.feature_fields] = df[featurizer.feature_fields].apply(pd.to_numeric)
    X_shard = df.as_matrix(columns=featurizer.feature_fields)
    #df[featurizer.__class__.__name__] = X_shard.tolist()
    df[featurizer.__class__.__name__] = [np.array(elt) for elt in X_shard.tolist()]
    ############################################################## DEBUG
    print("X_shard")
    print(X_shard)
    print("type(X_shard)")
    print(type(X_shard))
    print("[type(elt) for elt in X_shard.tolist()]")
    print([type(elt) for elt in X_shard.tolist()])
    #for ind, row in df.iterrows():
    #  # pandas rows are tuples (row_num, row_data)
    #  feature_list = []
    #  for feature_name in featurizer.feature_fields:
    #    feature_list.append(row[feature_name])
    #  features_data.append(np.array(feature_list))
    #df[featurizer.__class__.__name__] = features_data
    ############################################################## DEBUG
    time2 = time.time()
    print("USER SPECIFIED PROCESSING TOOK %0.3f s" % (time2-time1))
    ############################################################## DEBUG
