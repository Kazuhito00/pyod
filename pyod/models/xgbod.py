# -*- coding: utf-8 -*-
"""XGBOD: Improving Supervised Outlier Detection with Unsupervised
Representation Learning. A semi-supervised outlier detection framework.
"""
# Author: Yue Zhao <yuezhao@cs.toronto.edu>
# License: BSD 2 clause

try:
    # import xgboost as xgb
    from xgboost.sklearn import XGBClassifier

except ImportError:
    pass
    print('xgb not available')

import numpy as np
from sklearn.metrics import roc_auc_score
from sklearn.utils import check_array
from sklearn.utils.validation import check_is_fitted
from sklearn.utils.validation import check_X_y

from .base import BaseDetector
from .knn import KNN
from .lof import LOF
from .iforest import IForest
from .hbos import HBOS
from .ocsvm import OCSVM

from ..utils.utility import check_parameter
from ..utils.utility import check_detector
from ..utils.utility import standardizer
from ..utils.utility import precision_n_scores


class XGBOD(BaseDetector):
    """XGBOD class for outlier detection.
    It first use the passed in unsupervised outlier detectors to extract
    richer representation of the data and then concatenate the newly
    generated features to the original feature for constructing the augmented
    feature space. An XGBoost classifier is then applied on this augmented
    feature space. Read more in the :cite:`zhao2018xgbod`.

    Parameters
    ----------
    estimator_list : list, optional (default=None)
        The list of pyod detectors passed in for unsupervised learning

    standardization_flag_list : list, optional (default=None)
        The list of boolean flags for indicating whether to take
        standardization for each detector.

    max_depth : int
        Maximum tree depth for base learners.

    learning_rate : float
        Boosting learning rate (xgb's "eta")

    n_estimators : int
        Number of boosted trees to fit.

    silent : boolean
        Whether to print messages while running boosting.

    objective : string or callable
        Specify the learning task and the corresponding learning objective or
        a custom objective function to be used (see note below).

    booster : string
        Specify which booster to use: gbtree, gblinear or dart.

    n_jobs : int
        Number of parallel threads used to run xgboost.  (replaces ``nthread``)

    gamma : float
        Minimum loss reduction required to make a further partition on a leaf
        node of the tree.

    min_child_weight : int
        Minimum sum of instance weight(hessian) needed in a child.

    max_delta_step : int
        Maximum delta step we allow each tree's weight estimation to be.

    subsample : float
        Subsample ratio of the training instance.

    colsample_bytree : float
        Subsample ratio of columns when constructing each tree.

    colsample_bylevel : float
        Subsample ratio of columns for each split, in each level.

    reg_alpha : float (xgb's alpha)
        L1 regularization term on weights.

    reg_lambda : float (xgb's lambda)
        L2 regularization term on weights.

    scale_pos_weight : float
        Balancing of positive and negative weights.

    base_score:
        The initial prediction score of all instances, global bias.

    random_state : int
        Random number seed.  (replaces seed)

    missing : float, optional
        Value in the data which needs to be present as a missing value. If
        None, defaults to np.nan.

    importance_type: string, default "gain"
        The feature importance type for the ``feature_importances_``
        property: either "gain",
        "weight", "cover", "total_gain" or "total_cover".

    \*\*kwargs : dict, optional
        Keyword arguments for XGBoost Booster object.  Full documentation of
        parameters can be found here:
        https://github.com/dmlc/xgboost/blob/master/doc/parameter.rst.
        Attempting to set a parameter via the constructor args and \*\*kwargs
        dict simultaneously will result in a TypeError.

        Note: \*\*kwargs is unsupported by scikit-learn. We do not
        guarantee that parameters passed via this argument will interact
        properly with scikit-learn.

    Attributes
    ----------
    n_detector_ : int
        The number of unsupervised of detectors used.

    clf_ : object
        The XGBoost classifier.

    decision_scores_ : numpy array of shape (n_samples,)
        The outlier scores of the training data.
        The higher, the more abnormal. Outliers tend to have higher
        scores. This value is available once the detector is fitted.

    labels_ : int, either 0 or 1
        The binary labels of the training data. 0 stands for inliers
        and 1 for outliers/anomalies. It is generated by applying
        ``threshold_`` on ``decision_scores_``.

    """

    def __init__(self, estimator_list=None, standardization_flag_list=None,
                 max_depth=3, learning_rate=0.1,
                 n_estimators=100, silent=True,
                 objective="binary:logistic", booster='gbtree',
                 n_jobs=1, nthread=None, gamma=0, min_child_weight=1,
                 max_delta_step=0, subsample=1, colsample_bytree=1,
                 colsample_bylevel=1,
                 reg_alpha=0, reg_lambda=1, scale_pos_weight=1,
                 base_score=0.5, random_state=0, missing=None,
                 **kwargs):
        super(XGBOD, self).__init__()
        self.estimator_list = estimator_list
        self.standardization_flag_list = standardization_flag_list
        self.max_depth = max_depth
        self.learning_rate = learning_rate
        self.n_estimators = n_estimators
        self.silent = silent
        self.objective = objective
        self.booster = booster
        self.n_jobs = n_jobs
        self.nthread = nthread
        self.gamma = gamma
        self.min_child_weight = min_child_weight
        self.max_delta_step = max_delta_step
        self.subsample = subsample
        self.colsample_bytree = colsample_bytree
        self.colsample_bylevel = colsample_bylevel
        self.reg_alpha = reg_alpha
        self.reg_lambda = reg_lambda
        self.scale_pos_weight = scale_pos_weight
        self.base_score = base_score
        self.random_state = random_state
        self.missing = missing
        self.kwargs = kwargs

    def _init_detectors(self, X):
        """initialize unsupervised detectors if no predefined detectors is
        provided.

        Parameters
        ----------
        X : numpy array of shape (n_samples, n_features)
            The train data

        Returns
        -------
        estimator_list : list of object
            The initialized list of detectors

        standardization_flag_list : list of boolean
            The list of bool flag to indicate whether standardization is needed

        """
        estimator_list = []
        standardization_flag_list = []

        # predefined range of n_neighbors for KNN, AvgKNN, and LOF
        k_range = [1, 3, 5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]

        # validate the value of k
        k_range = [k for k in k_range if k < X.shape[0]]

        for k in k_range:
            estimator_list.append(KNN(n_neighbors=k, method='largest'))
            estimator_list.append(KNN(n_neighbors=k, method='mean'))
            estimator_list.append(LOF(n_neighbors=k))
            standardization_flag_list.append(True)
            standardization_flag_list.append(True)
            standardization_flag_list.append(True)

        n_bins_range = [3, 5, 7, 9, 12, 15, 20, 25, 30, 50]
        for n_bins in n_bins_range:
            estimator_list.append(HBOS(n_bins=n_bins))
            standardization_flag_list.append(False)

        # predefined range of nu for one-class svm
        nu_range = [0.01, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.99]
        for nu in nu_range:
            estimator_list.append(OCSVM(nu=nu, random_state=self.random_state))
            standardization_flag_list.append(True)

        # predefined range for number of estimators in isolation forests
        n_range = [10, 20, 50, 70, 100, 150, 200, 250]
        for n in n_range:
            estimator_list.append(
                IForest(n_estimators=n, random_state=self.random_state))
            standardization_flag_list.append(False)

        return estimator_list, standardization_flag_list

    def _validate_estimator(self, X):
        if self.estimator_list is None:
            self.estimator_list, \
            self.standardization_flag_list = self._init_detectors(X)

        # perform standardization for all detectors by default
        if self.standardization_flag_list is None:
            self.standardization_flag_list = [True] * len(self.estimator_list)

        # validate two lists length
        if len(self.estimator_list) != len(self.standardization_flag_list):
            raise ValueError(
                "estimator_list length ({0}) is not equal "
                "to standardization_flag_list length ({1})".format(
                    len(self.estimator_list),
                    len(self.standardization_flag_list)))

        # validate the estimator list is not empty
        check_parameter(len(self.estimator_list), low=1,
                        param_name='number of estimators',
                        include_left=True, include_right=True)

        for estimator in self.estimator_list:
            check_detector(estimator)

        return len(self.estimator_list)

    def _generate_new_features(self, X):
        X_add = np.zeros([X.shape[0], self.n_detector_])

        # keep the standardization scalar for test conversion
        X_norm = self._scalar.transform(X)

        for ind, estimator in enumerate(self.estimator_list):
            if self.standardization_flag_list[ind]:
                X_add[:, ind] = estimator.decision_function(X_norm)

            else:
                X_add[:, ind] = estimator.decision_function(X)
        return X_add

    def fit(self, X, y):
        """Fit the model using X and y as training data.

        Parameters
        ----------
        X : numpy array of shape (n_samples, n_features)
            Training data.

        y : numpy array of shape (n_samples,)
            The ground truth (binary label)

            - 0 : inliers
            - 1 : outliers

        Returns
        -------
        self : object
        """

        # Validate inputs X and y
        X, y = check_X_y(X, y)
        X = check_array(X)
        self._set_n_classes(y)
        self.n_detector_ = self._validate_estimator(X)
        self.X_train_add_ = np.zeros([X.shape[0], self.n_detector_])

        # keep the standardization scalar for test conversion
        X_norm, self._scalar = standardizer(X, keep_scalar=True)

        for ind, estimator in enumerate(self.estimator_list):
            if self.standardization_flag_list[ind]:
                estimator.fit(X_norm)
                self.X_train_add_[:, ind] = estimator.decision_scores_

            else:
                estimator.fit(X)
                self.X_train_add_[:, ind] = estimator.decision_scores_

        # construct the new feature space
        self.X_train_new_ = np.concatenate((X, self.X_train_add_), axis=1)

        # initialize, train, and predict on XGBoost
        self.clf_ = clf = XGBClassifier(max_depth=self.max_depth,
                                        learning_rate=self.learning_rate,
                                        n_estimators=self.n_estimators,
                                        silent=self.silent,
                                        objective=self.objective,
                                        booster=self.booster,
                                        n_jobs=self.n_jobs,
                                        nthread=self.nthread,
                                        gamma=self.gamma,
                                        min_child_weight=self.min_child_weight,
                                        max_delta_step=self.max_delta_step,
                                        subsample=self.subsample,
                                        colsample_bytree=self.colsample_bytree,
                                        colsample_bylevel=self.colsample_bylevel,
                                        reg_alpha=self.reg_alpha,
                                        reg_lambda=self.reg_lambda,
                                        scale_pos_weight=self.scale_pos_weight,
                                        base_score=self.base_score,
                                        random_state=self.random_state,
                                        missing=self.missing,
                                        **self.kwargs)
        self.clf_.fit(self.X_train_new_, y)
        self.decision_scores_ = self.clf_.predict_proba(
            self.X_train_new_)[:, 1]
        self.labels_ = self.clf_.predict(self.X_train_new_).ravel()

        return self

    def decision_function(self, X):

        check_is_fitted(self, ['clf_', 'decision_scores_',
                               'labels_', '_scalar'])

        X = check_array(X)

        # construct the new feature space
        X_add = self._generate_new_features(X)
        X_new = np.concatenate((X, X_add), axis=1)

        pred_scores = self.clf_.predict_proba(X_new)[:, 1]
        return pred_scores.ravel()

    def predict(self, X):
        """Predict if a particular sample is an outlier or not.
        Calling xgboost `predict` function.

        Parameters
        ----------
        X : numpy array of shape (n_samples, n_features)
            The input samples.

        Returns
        -------
        outlier_labels : numpy array of shape (n_samples,)
            For each observation, tells whether or not
            it should be considered as an outlier according to the
            fitted model. 0 stands for inliers and 1 for outliers.
        """

        check_is_fitted(self, ['clf_', 'decision_scores_',
                               'labels_', '_scalar'])

        X = check_array(X)

        # construct the new feature space
        X_add = self._generate_new_features(X)
        X_new = np.concatenate((X, X_add), axis=1)

        pred_scores = self.clf_.predict(X_new)
        return pred_scores.ravel()

    def predict_proba(self, X):
        """Predict the probability of a sample being outlier.
        Calling xgboost `predict_proba` function.

        Parameters
        ----------
        X : numpy array of shape (n_samples, n_features)
            The input samples.


        Returns
        -------
        outlier_labels : numpy array of shape (n_samples,)
            For each observation, tells whether or not
            it should be considered as an outlier according to the
            fitted model. Return the outlier probability, ranging
            in [0,1].
        """
        return self.decision_function(X)

    def fit_predict(self, X, y):
        self.fit(X, y)
        return self.labels_

    def fit_predict_score(self, X, y, scoring='roc_auc_score'):
        """Fit the detector, predict on samples, and evaluate the model by
        predefined metrics, e.g., ROC.

        Parameters
        ----------
        X : numpy array of shape (n_samples, n_features)
            The input samples.

        y : numpy array of shape (n_samples,), optional (default=None)
            The ground truth of the input samples (labels).

        scoring : str, optional (default='roc_auc_score')
            Evaluation metric:

            - 'roc_auc_score': ROC score
            - 'prc_n_score': Precision @ rank n score

        Returns
        -------
        score : float
        """

        self.fit(X, y)

        if scoring == 'roc_auc_score':
            score = roc_auc_score(y, self.decision_scores_)
        elif scoring == 'prc_n_score':
            score = precision_n_scores(y, self.decision_scores_)
        else:
            raise NotImplementedError('PyOD built-in scoring only supports '
                                      'ROC and Precision @ rank n')

        print("{metric}: {score}".format(metric=scoring, score=score))

        return score
