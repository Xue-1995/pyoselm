"""Module to build Online Sequential Extreme Learning Machine (OS-ELM) models"""

# ===================================================
# Author: Leandro Ferrado
# Copyright(c) 2018
# License: Apache License 2.0
# ===================================================

import warnings

import numpy as np
from scipy.linalg import pinv2
from scipy.special import softmax
from sklearn.base import RegressorMixin, ClassifierMixin, BaseEstimator
from sklearn.metrics import accuracy_score
from sklearn.preprocessing import LabelBinarizer
from sklearn.utils import as_float_array
from sklearn.utils.extmath import safe_sparse_dot

from pyoselm.layer import MLPRandomLayer


__all__ = [
    "OSELMRegressor",
    "OSELMClassifier",
    "OSELMClassifierSoftmax",
]


def multiple_safe_sparse_dot(*matrices):
    """
    Make safe_sparse_dot() calls over multiple matrices

    Parameters
    ----------
    matrices: iterable of matrices

    Returns
    -------
    dot_product : array or sparse matrix
    """
    if len(matrices) < 2:
        raise ValueError("Argument 'matrices' must have at least 2 matrices")

    r = matrices[0]
    for m in matrices[1:]:
        r = safe_sparse_dot(r, m)

    return r


class OSELMRegressor(BaseEstimator, RegressorMixin):
    """
    OSELMRegressor is a regressor based on Online Sequential
    Extreme Learning Machine (OS-ELM).

    This type of model is an ELM that....
    [1][2]

    Parameters
    ----------
    `n_hidden` : int, optional (default=20)
        Number of units to generate in the SimpleRandomLayer

    `activation_func` : {callable, string} optional (default='sigmoid')
        Function used to transform input activation

        It must be one of 'tanh', 'sine', 'tribas', 'inv_tribase', 'sigmoid',
        'hardlim', 'softlim', 'gaussian', 'multiquadric', 'inv_multiquadric' or
        a callable.  If none is given, 'tanh' will be used. If a callable
        is given, it will be used to compute the hidden unit activations.

    `activation_args` : dictionary, optional (default=None)
        Supplies keyword arguments for a callable activation_func

    `use_woodbury`  : bool, optional (default=False)
        Flag to indicate if Woodbury formula should be used for the fit
        step, or just the traditional iterative procedure. Not recommended if
        handling large datasets.

    `random_state`  : int, RandomState instance or None (default=None)
        Control the pseudo random number generator used to generate the
        hidden unit weights at fit time.

    Attributes
    ----------
    `P` : np.array
        ...

    `beta` : np.array
    ...

    See Also
    --------
    ELMRegressor, MLPRandomLayer

    References
    ----------
    .. [1] http://www.extreme-learning-machines.org
    .. [2] G.-B. Huang, Q.-Y. Zhu and C.-K. Siew, "Extreme Learning Machine:
          Theory and Applications", Neurocomputing, vol. 70, pp. 489-501,
              2006.

    """
    def __init__(self,
                 n_hidden=20,
                 activation_func='sigmoid',
                 activation_args=None,
                 use_woodbury=False,
                 random_state=123,):
        self.n_hidden = n_hidden
        self.random_state = random_state
        self.activation_func = activation_func
        self.activation_args = activation_args
        self.use_woodbury = use_woodbury

        self.P = None
        self.beta = None

    def _create_random_layer(self):
        """Pass init params to MLPRandomLayer"""

        return MLPRandomLayer(n_hidden=self.n_hidden,
                              random_state=self.random_state,
                              activation_func=self.activation_func,
                              activation_args=self.activation_args)

    def _fit_woodbury(self, X, y):
        """Compute learning step using Woodbury formula"""
        # fit random hidden layer and compute the hidden layer activations
        H = self._create_random_layer().fit_transform(X)
        y = as_float_array(y, copy=True)

        if self.beta is None:
            # this is the first time the model is fitted
            if len(X) < self.n_hidden:
                raise ValueError("The first time the model is fitted, "
                                 "X must have at least equal number of "
                                 "samples than n_hidden value!")
            # TODO: handle cases of singular matrices (maybe with a try clause)
            self.P = pinv2(safe_sparse_dot(H.T, H))
            self.beta = multiple_safe_sparse_dot(self.P, H.T, y)
        else:
            if len(H) > 10e3:
                warnings.warn(f"Large input of {len(H)} rows and use_woodbury=True "
                              f"may throw OOM errors")

            M = np.eye(len(H)) + multiple_safe_sparse_dot(H, self.P, H.T)  # TODO: sparse np.eye?
            self.P -= multiple_safe_sparse_dot(self.P, H.T, pinv2(M), H, self.P)
            e = y - safe_sparse_dot(H, self.beta)
            self.beta += multiple_safe_sparse_dot(self.P, H.T, e)

    def _fit_iterative(self, X, y):
        """Compute learning step using iterative procedure"""
        # fit random hidden layer and compute the hidden layer activations
        H = self._create_random_layer().fit_transform(X)
        y = as_float_array(y, copy=True)

        if self.beta is None:
            # this is the first time the model is fitted
            if len(X) < self.n_hidden:
                raise ValueError("The first time the model is fitted, "
                                 "X must have at least equal number of "
                                 "samples than n_hidden value!")

            self.P = safe_sparse_dot(H.T, H)
            P_inv = pinv2(self.P)
            self.beta = multiple_safe_sparse_dot(P_inv, H.T, y)
        else:
            self.P += safe_sparse_dot(H.T, H)
            P_inv = pinv2(self.P)
            e = y - safe_sparse_dot(H, self.beta)
            self.beta += multiple_safe_sparse_dot(P_inv, H.T, e)

    def fit(self, X, y):
        """
        Fit the model using X, y as training data.

        Notice that this function could be used for n_samples==1 (online learning),
        except for the first time the model is fitted, where it needs at least as 
        many rows as 'n_hidden' configured.

        Parameters
        ----------
        X : {array-like, sparse matrix} of shape [n_samples, n_features]
            Training vectors, where n_samples is the number of samples
            and n_features is the number of features.

        y : array-like of shape [n_samples, n_outputs]
            Target values (class labels in classification, real numbers in
            regression)

        Returns
        -------
        self : object

            Returns an instance of self.
        """
        if self.use_woodbury:
            self._fit_woodbury(X, y)
        else:
            self._fit_iterative(X, y)

        return self

    def predict(self, X):
        """
        Predict values using the model

        Parameters
        ----------
        X : {array-like, sparse matrix} of shape [n_samples, n_features]

        Returns
        -------
        C : numpy array of shape [n_samples, n_outputs]
            Predicted values.
        """
        if self.beta is None:
            raise ValueError("OSELMRegressor not fitted")

        # compute hidden layer activations
        H = self._create_random_layer().fit_transform(X)

        # compute output predictions for new hidden activations
        predictions = safe_sparse_dot(H, self.beta)

        return predictions


class OSELMClassifier(OSELMRegressor):
    """
    ELMClassifier is a classifier based on the Extreme Learning Machine.

    An Extreme Learning Machine (ELM) is a single layer feedforward
    network with a random hidden layer components and ordinary linear
    least squares fitting of the hidden->output weights by default.
    [1][2]

    ELMClassifier is an ELMRegressor subclass that first binarizes the
    data, then uses the superclass to compute the decision function that
    is then unbinarized to yield the prediction.

    The params for the RandomLayer used in the input transform are
    exposed in the ELMClassifier constructor.

    Parameters
    ----------
    `n_hidden` : int, optional (default=20)
        Number of units to generate in the SimpleRandomLayer

    `activation_func` : {callable, string} optional (default='sigmoid')
        Function used to transform input activation

        It must be one of 'tanh', 'sine', 'tribas', 'inv_tribase', 'sigmoid',
        'hardlim', 'softlim', 'gaussian', 'multiquadric', 'inv_multiquadric' or
        a callable.  If none is given, 'tanh' will be used. If a callable
        is given, it will be used to compute the hidden unit activations.

    `activation_args` : dictionary, optional (default=None)
        Supplies keyword arguments for a callable activation_func

    `random_state`  : int, RandomState instance or None (default=None)
        Control the pseudo random number generator used to generate the
        hidden unit weights at fit time.

    Attributes
    ----------
    `classes_` : numpy array of shape [n_classes]
        Array of class labels

    See Also
    --------
    ELMRegressor, OSELMRegressor, MLPRandomLayer

    References
    ----------
    .. [1] http://www.extreme-learning-machines.org
    .. [2] G.-B. Huang, Q.-Y. Zhu and C.-K. Siew, "Extreme Learning Machine:
          Theory and Applications", Neurocomputing, vol. 70, pp. 489-501,
              2006.
    """

    def __init__(self,
                 n_hidden=20,
                 activation_func='sigmoid',
                 activation_args=None,
                 binarizer=LabelBinarizer(-1, 1),
                 use_woodbury=False,
                 random_state=123):

        super(OSELMClassifier, self).__init__(n_hidden=n_hidden,
                                              random_state=random_state,
                                              activation_func=activation_func,
                                              activation_args=activation_args,
                                              use_woodbury=use_woodbury)
        self.classes_ = None
        self.binarizer = binarizer

    def decision_function(self, X):
        """
        This function return the decision function values related to each
        class on an array of test vectors X.

        Parameters
        ----------
        X : array-like of shape [n_samples, n_features]

        Returns
        -------
        C : array of shape [n_samples, n_classes] or [n_samples,]
            Decision function values related to each class, per sample.
            In the two-class case, the shape is [n_samples,]
        """
        return super(OSELMClassifier, self).predict(X)

    def fit(self, X, y):
        """
        Fit the model using X, y as training data.

        Parameters
        ----------
        X : {array-like, sparse matrix} of shape [n_samples, n_features]
            Training vectors, where n_samples is the number of samples
            and n_features is the number of features.

        y : array-like of shape [n_samples, n_outputs]
            Target values (class labels in classification, real numbers in
            regression)

        Returns
        -------
        self : object

            Returns an instance of self.
        """
        self.classes_ = np.unique(y)

        y_bin = self.binarizer.fit_transform(y)

        super(OSELMClassifier, self).fit(X, y_bin)

        return self

    # TODO: partial_fit

    def predict(self, X):
        """
        Predict class values using the model

        Parameters
        ----------
        X : {array-like, sparse matrix} of shape [n_samples, n_features]

        Returns
        -------
        C : numpy array of shape [n_samples, n_outputs]
            Predicted class values.
        """
        raw_predictions = self.decision_function(X)
        class_predictions = self.binarizer.inverse_transform(raw_predictions)

        return class_predictions
    
    def predict_proba(self, X):
        """
        Predict probability values using the model

        Parameters
        ----------
        X : {array-like, sparse matrix} of shape [n_samples, n_features]

        Returns
        -------
        P : numpy array of shape [n_samples, n_outputs]
            Predicted probability values.
        """
        raw_predictions = self.decision_function(X)
        # using softmax to translate raw predictions into probability values
        proba_predictions = softmax(raw_predictions)

        return proba_predictions

    def score(self, X, y, **kwargs):
        """Force use of accuracy score since
        it doesn't inherit from ClassifierMixin"""
        return accuracy_score(y, self.predict(X))


# TODO: remove this
class OSELMClassifierSoftmax(OSELMClassifier):
    """
    ELMClassifier is a classifier based on the Extreme Learning Machine.

    ???


    An Extreme Learning Machine (ELM) is a single layer feedforward
    network with a random hidden layer components and ordinary linear
    least squares fitting of the hidden->output weights by default.
    [1][2]

    ELMClassifier is an ELMRegressor subclass that first binarizes the
    data, then uses the superclass to compute the decision function that
    is then unbinarized to yield the prediction.

    The params for the RandomLayer used in the input transform are
    exposed in the ELMClassifier constructor.

    Parameters
    ----------
    `n_hidden` : int, optional (default=20)
        Number of units to generate in the SimpleRandomLayer

    `activation_func` : {callable, string} optional (default='sigmoid')
        Function used to transform input activation

        It must be one of 'tanh', 'sine', 'tribas', 'inv_tribase', 'sigmoid',
        'hardlim', 'softlim', 'gaussian', 'multiquadric', 'inv_multiquadric' or
        a callable.  If none is given, 'tanh' will be used. If a callable
        is given, it will be used to compute the hidden unit activations.

    `activation_args` : dictionary, optional (default=None)
        Supplies keyword arguments for a callable activation_func

    `random_state`  : int, RandomState instance or None (default=None)
        Control the pseudo random number generator used to generate the
        hidden unit weights at fit time.

    Attributes
    ----------
    `classes_` : numpy array of shape [n_classes]
        Array of class labels

    See Also
    --------
    RandomLayer, RBFRandomLayer, MLPRandomLayer,
    GenELMRegressor, GenELMClassifier, ELMClassifier

    References
    ----------
    .. [1] http://www.extreme-learning-machines.org
    .. [2] G.-B. Huang, Q.-Y. Zhu and C.-K. Siew, "Extreme Learning Machine:
          Theory and Applications", Neurocomputing, vol. 70, pp. 489-501,
              2006.
    """

    def __init__(self,
                 n_hidden=20,
                 n_classes=None,
                 activation_func='sigmoid',
                 activation_args=None,
                 random_state=123):

        super(OSELMClassifierSoftmax, self).__init__(
            n_hidden=n_hidden,
            random_state=random_state,
            activation_func=activation_func,
            activation_args=activation_args
        )

        self.binarizer = LabelBinarizer(0, 1)

        if n_classes is not None:
            self.classes_ = range(n_classes)
            self.binarizer.fit(self.classes_)
        else:
            self.classes_ = None

    def fit(self, X, y):
        """
        Fit the model using X, y as training data.

        Parameters
        ----------
        X : {array-like, sparse matrix} of shape [n_samples, n_features]
            Training vectors, where n_samples is the number of samples
            and n_features is the number of features.

        y : array-like of shape [n_samples, n_outputs]
            Target values (class labels in classification, real numbers in
            regression)

        Returns
        -------
        self : object

            Returns an instance of self.
        """
        if self.classes_ is None:
            self.classes_ = np.unique(y)
            y_bin = self.binarizer.fit_transform(y)
        else:
            y_bin = self.binarizer.transform(y)

        super(OSELMClassifier, self).fit(X, y_bin)

        return self

    @staticmethod
    def _softmax(p):
        if not isinstance(p, np.ndarray):
            p = np.asarray(p)

        if len(p.shape) == 1:
            p = np.expand_dims(p, axis=0)

        max_p = np.max(p, axis=1)
        exp_p = np.asarray([np.exp(p_i - max_p) for p_i in p.T]).T
        sum_exp_p = np.sum(exp_p, axis=1, dtype=np.float64)
        softmax_p = np.asarray([exp_p_i / sum_exp_p for exp_p_i in exp_p.T]).T
        return softmax_p

    def predict(self, X):
        """
        Predict values using the model

        Parameters
        ----------
        X : {array-like, sparse matrix} of shape [n_samples, n_features]

        Returns
        -------
        C : numpy array of shape [n_samples, n_outputs]
            Predicted values.
        """
        raw_predictions = self.decision_function(X)
        class_predictions = self.binarizer.inverse_transform(raw_predictions)
        return class_predictions

    def predict_proba(self, X):
        raw_predictions = self.decision_function(X)
        probs_predictions = self._softmax(raw_predictions)
        return probs_predictions
