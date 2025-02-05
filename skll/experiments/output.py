# License: BSD 3 clause
"""
Functions related to running experiments and parsing configuration files.

:author: Dan Blanchard (dblanchard@ets.org)
:author: Michael Heilman (mheilman@ets.org)
:author: Nitin Madnani (nmadnani@ets.org)
:author: Chee Wee Leong (cleong@ets.org)
"""

from __future__ import annotations

import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import IO, Any, Dict, List, Tuple

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from ruamel.yaml import YAML

from skll.types import FoldMapping, PathOrStr
from skll.utils.logging import get_skll_logger

# Turn off interactive plotting for matplotlib
plt.ioff()


def _compute_ylimits_for_featureset(
    df: pd.DataFrame, metrics: List[str]
) -> Dict[str, Tuple[float, float]]:
    """
    Compute the y-limits for learning curve score plots.

    Parameters
    ----------
    df : pd.DataFrame
        A data_frame with relevant metric information for
        train and test.
    metrics : List[str]
        A list of metrics for learning curve plots.

    Returns
    -------
    ylimits : Dict[str, Tuple[float, float]]
        A dictionary, with metric names as keys
        and a tuple of (lower_limit, upper_limit) as values.
    """
    # set the y-limits of the curves depending on what kind
    # of values the metric produces
    ylimits = {}
    for metric in metrics:
        # get the real min and max for the values that will be plotted
        df_train = df[(df["variable"] == "train_score_mean") & (df["metric"] == metric)]
        df_test = df[(df["variable"] == "test_score_mean") & (df["metric"] == metric)]
        train_values_lower = df_train["value"].values - df_train["train_score_std"].values
        test_values_lower = df_test["value"].values - df_test["test_score_std"].values
        min_score = np.min(np.concatenate([train_values_lower, test_values_lower]))
        train_values_upper = df_train["value"].values + df_train["train_score_std"].values
        test_values_upper = df_test["value"].values + df_test["test_score_std"].values
        max_score = np.max(np.concatenate([train_values_upper, test_values_upper]))

        # squeeze the limits to hide unnecessary parts of the graph
        # set the limits with a little buffer on either side but not too much
        if min_score < 0:
            lower_limit = max(min_score - 0.1, math.floor(min_score) - 0.05)
        else:
            lower_limit = 0

        if max_score > 0:
            upper_limit = min(max_score + 0.1, math.ceil(max_score) + 0.05)
        else:
            upper_limit = 0

        ylimits[metric] = (lower_limit, upper_limit)

    return ylimits


def _generate_learning_curve_score_plots(
    df_scores: pd.DataFrame,
    num_metrics: int,
    num_learners: int,
    experiment_name: str,
    output_dir: PathOrStr,
    rotate_labels: bool = False,
) -> None:
    """
    Generate learning curve score plots, one per featureset.

    This function generates score-based learning curve plots, i.e., plots
    where the training set size is on the x-axis and the training and
    cross-validation scores are on the y-axis. The plots are faceted, with
    different metrics along the rows and different learners along the columns.

    Parameters
    ----------
    df_scores : pandas.DataFrame
        The pandas data frame containing the various scores to be plotted.
    num_metrics : int
        The number of metrics specified in the experiment.
    num_learners: int
        The number of learners specified in the experiment.
    experiment_name : str
        The name of the experiment.
    output_dir : :class:`skll.types.PathOrStr`
        Path to the output directory for the plots.
    rotate_labels : bool, default=False
        Whether to rotate the x-axis labels for the training data size.
    """
    # convert output dir to a path
    output_dir = Path(output_dir)

    # set up and draw the actual learning curve figures, one for
    # each of the featuresets
    for fs_name, df_fs in df_scores.groupby("featureset_name"):
        fig = plt.figure()
        fig.set_size_inches(2.5 * num_learners, 2.5 * num_metrics)

        # compute ylimits for this feature set for each objective
        with sns.axes_style("whitegrid", {"grid.linestyle": ":", "xtick.major.size": 3.0}):
            g = sns.FacetGrid(
                df_fs,
                row="metric",
                col="learner_name",
                height=2.5,
                aspect=1,
                margin_titles=True,
                despine=True,
                sharex=False,
                sharey=False,
                legend_out=False,
            )
            train_color, test_color = sns.color_palette(palette="Set1", n_colors=2)
            g = g.map_dataframe(
                sns.pointplot,
                x="training_set_size",
                y="value",
                hue="variable",
                scale=0.5,
                errorbar=None,
                palette={"train_score_mean": train_color, "test_score_mean": test_color},
            )
            ylimits = _compute_ylimits_for_featureset(df_fs, g.row_names)
            for ax in g.axes.flat:
                plt.setp(ax.texts, text="")
            g = g.set_titles(row_template="", col_template="{col_name}").set_axis_labels(
                "Training Examples", "Score"
            )
            if rotate_labels:
                g = g.set_xticklabels(rotation=60)

            for i, row_name in enumerate(g.row_names):
                for j, col_name in enumerate(g.col_names):
                    ax = g.axes[i][j]
                    ax.set(ylim=ylimits[row_name])
                    df_ax_train = df_fs[
                        (df_fs["learner_name"] == col_name)
                        & (df_fs["metric"] == row_name)
                        & (df_fs["variable"] == "train_score_mean")
                    ]
                    df_ax_test = df_fs[
                        (df_fs["learner_name"] == col_name)
                        & (df_fs["metric"] == row_name)
                        & (df_fs["variable"] == "test_score_mean")
                    ]
                    ax.fill_between(
                        list(range(len(df_ax_train))),
                        df_ax_train["value"] - df_ax_train["train_score_std"],
                        df_ax_train["value"] + df_ax_train["train_score_std"],
                        alpha=0.1,
                        color=train_color,
                    )
                    ax.fill_between(
                        list(range(len(df_ax_test))),
                        df_ax_test["value"] - df_ax_test["test_score_std"],
                        df_ax_test["value"] + df_ax_test["test_score_std"],
                        alpha=0.1,
                        color=test_color,
                    )
                    if j == 0:
                        ax.set_ylabel(row_name)
                        if i == 0:
                            # set up the legend handles for this plot
                            plot_handles = [
                                matplotlib.lines.Line2D(
                                    [], [], color=color, label=label, linestyle="-"
                                )
                                for color, label in zip(
                                    [train_color, test_color], ["Training", "Cross-validation"]
                                )
                            ]
                            ax.legend(
                                handles=plot_handles,
                                loc=4,
                                fancybox=True,
                                fontsize="x-small",
                                ncol=1,
                                frameon=True,
                            )
            g.fig.tight_layout(w_pad=1)
            plt.savefig(output_dir / f"{experiment_name}_{fs_name}.png", dpi=300)
            # explicitly close figure to save memory
            plt.close(fig)


def _generate_learning_curve_time_plots(
    df_times: pd.DataFrame,
    num_learners: int,
    experiment_name: str,
    output_dir: PathOrStr,
    rotate_labels: bool = False,
) -> None:
    """
    Generate learning curve time plots, one per featureset.

    This function generates time-based learning curve plots, i.e., plots
    where the training set size is on the x-axis and the model fit times
    are on the y-axis. The plots are faceted, with different learners
    along the columns. There is a single row.

    Parameters
    ----------
    df_times : pandas.DataFrame
        The pandas data frame containing the various fit times to be plotted.
    num_learners: int
        The number of learners specified in the experiment.
    experiment_name : str
        The name of the experiment.
    output_dir : :class:`skll.types.PathOrStr`
        Path to the output directory for the plots.
    rotate_labels : bool, default=False
        Whether to rotate the x-axis labels for the training data size.
    """
    # convert output dir to a path
    output_dir = Path(output_dir)

    # set up and draw the actual learning curve figures, one for
    # each of the featuresets
    for fs_name, df_fs in df_times.groupby("featureset_name"):
        fig = plt.figure()
        fig.set_size_inches(2.5 * num_learners, 2.5)

        # compute ylimits for this feature set for each metric
        with sns.axes_style("whitegrid", {"grid.linestyle": ":", "xtick.major.size": 3.0}):
            g = sns.FacetGrid(
                df_fs,
                col="learner_name",
                height=2.5,
                aspect=1,
                margin_titles=True,
                despine=True,
                sharex=False,
                sharey=True,
                legend_out=False,
            )
            g = g.map_dataframe(
                sns.pointplot,
                x="training_set_size",
                y="value",
                hue="variable",
                scale=0.5,
                errorbar=None,
            )
            # compute the upper and lower
            for ax in g.axes.flat:
                plt.setp(ax.texts, text="")
            g = g.set_titles(row_template="", col_template="{col_name}").set_axis_labels(
                "Training Examples", "Fit time (s)"
            )
            if rotate_labels:
                g = g.set_xticklabels(rotation=60)

            for j, col_name in enumerate(g.col_names):
                ax = g.axes[0][j]
                df_ax = df_fs[
                    (df_fs["learner_name"] == col_name) & (df_fs["variable"] == "fit_time_mean")
                ]
                ax.fill_between(
                    list(range(len(df_ax))),
                    df_ax["value"] - df_ax["fit_time_std"],
                    df_ax["value"] + df_ax["fit_time_std"],
                    alpha=0.1,
                )

            g.fig.tight_layout(w_pad=1)
            plt.savefig(output_dir / f"{experiment_name}_{fs_name}_times.png", dpi=300)

            # explicitly close figure to save memory
            plt.close(fig)


def generate_learning_curve_plots(
    experiment_name: str, output_dir: PathOrStr, learning_curve_tsv_file: PathOrStr
) -> None:
    """
    Generate learning curves using the TSV output file from a learning curve experiment.

    This function generates both the score plots as well as the fit time plots.

    Parameters
    ----------
    experiment_name : str
        The name of the experiment.
    output_dir : :class:`skll.types.PathOrStr`
        Path to the output directory for the plots.
    learning_curve_tsv_file : :class:`skll.types.PathOrStr`
        The path to the learning curve TSV file.
    """
    # convert output_dir to Path object
    output_dir = Path(output_dir)

    # use pandas to read in the TSV file into a data frame
    # and massage it from wide to long format for plotting
    df = pd.read_csv(learning_curve_tsv_file, sep="\t")
    num_learners = len(df["learner_name"].unique())
    num_metrics = len(df["metric"].unique())

    # if there are any training sizes greater than 1000,
    # then we should probably rotate the tick labels
    # since otherwise the labels are not clearly rendered
    rotate_labels = df["training_set_size"].unique().max() >= 1000

    # get the columns relevant to the two types of plots
    score_columns = [
        column
        for column in df.columns
        if column
        not in [
            "train_set_name",
            "fit_time_mean",
            "fit_time_std",
            "scikit_learn_version",
            "version",
        ]
    ]
    time_columns = [
        column
        for column in df.columns
        if column
        not in [
            "train_set_name",
            "train_score_mean",
            "train_score_std",
            "test_score_mean",
            "test_score_std",
            "scikit_learn_version",
            "version",
        ]
    ]

    # create the score-specific data frame
    df_score = df[score_columns].copy()
    df_score_melted = pd.melt(
        df_score,
        id_vars=[c for c in df_score.columns if c not in ["train_score_mean", "test_score_mean"]],
    )
    # make sure the "variable" column is categorical since it will be
    # mapped to hue levels in the learning curve below
    df_score_melted["variable"] = df_score_melted["variable"].astype("category")

    # also make sure that the "learner_name" column is categorical so that
    # it's sorted correctly
    df_score_melted["learner_name"] = df_score_melted["learner_name"].astype("category")

    # now compute the time-specific data frame
    df_time = df[time_columns].copy()

    # note that although we have already averaged the fit times over
    # the various training, we still have multiple fit times for each
    # of the metrics so we can further average those out
    df_time_indexed = df_time.set_index(
        ["featureset_name", "learner_name", "training_set_size", "metric"]
    )
    df_time = (
        df_time_indexed.groupby(level=["featureset_name", "learner_name", "training_set_size"])
        .mean()
        .reset_index()
    )

    # now let's melt the time data frame the same way that we did the score one
    df_time_melted = pd.melt(
        df_time,
        id_vars=[c for c in df_time.columns if c != "fit_time_mean"],
    )

    # also make sure that the "learner_name" column is categorical so that
    # it's sorted correctly
    df_time_melted["learner_name"] = df_time_melted["learner_name"].astype("category")

    # call the function to generate the score plots first
    _generate_learning_curve_score_plots(
        df_score_melted,
        num_metrics,
        num_learners,
        experiment_name,
        output_dir,
        rotate_labels=rotate_labels,
    )

    # now call the function to generate the time plots
    _generate_learning_curve_time_plots(
        df_time_melted,
        num_learners,
        experiment_name,
        output_dir,
        rotate_labels=rotate_labels,
    )


def _print_fancy_output(
    learner_result_dicts: List[Dict[str, Any]], output_file: IO[str] = sys.stdout
) -> None:
    """
    Print nice tables with all of the results from cross-validation folds.

    Parameters
    ----------
    learner_result_dicts : List[Dict[str, Any]]
        List of result dictionaries.
    output_file : IO[str], default=sys.stdout
        The file buffer to print to.
    """
    if not learner_result_dicts:
        raise ValueError("Result dictionary list is empty!")

    lrd = learner_result_dicts[0]
    print(f'Experiment Name: {lrd["experiment_name"]}', file=output_file)
    print(f'SKLL Version: {lrd["version"]}', file=output_file)
    print(f'Training Set: {lrd["train_set_name"]}', file=output_file)
    print(f'Training Set Size: {lrd["train_set_size"]}', file=output_file)
    print(f'Test Set: {lrd["test_set_name"]}', file=output_file)
    print(f'Test Set Size: {lrd["test_set_size"]}', file=output_file)
    print(f'Shuffle: {lrd["shuffle"]}', file=output_file)
    print(f'Feature Set: {lrd["featureset"]}', file=output_file)
    print(f'Learner: {lrd["learner_name"]}', file=output_file)
    print(f'Task: {lrd["task"]}', file=output_file)
    if lrd["folds_file"]:
        print(f'Specified Folds File: {lrd["folds_file"]}', file=output_file)
    if lrd["task"] == "cross_validate":
        print(f'Number of Folds: {lrd["cv_folds"]}', file=output_file)
        if not lrd["cv_folds"].endswith("folds file"):
            print(f'Stratified Folds: {lrd["stratified_folds"]}', file=output_file)
    print(f'Feature Scaling: {lrd["feature_scaling"]}', file=output_file)
    print(f'Grid Search: {lrd["grid_search"]}', file=output_file)
    if lrd["grid_search"]:
        print(f'Grid Search Folds: {lrd["grid_search_folds"]}', file=output_file)
        print(f'Grid Objective Function: {lrd["grid_objective"]}', file=output_file)
    if (
        lrd["task"] == "cross_validate"
        and lrd["grid_search"]
        and lrd["cv_folds"].endswith("folds file")
    ):
        print(
            "Using Folds File for Grid Search: " f'{lrd["use_folds_file_for_grid_search"]}',
            file=output_file,
        )
    if lrd["task"] in ["evaluate", "cross_validate"] and lrd["additional_scores"]:
        print(
            "Additional Evaluation Metrics: " f'{list(lrd["additional_scores"].keys())}',
            file=output_file,
        )
    print(f'Scikit-learn Version: {lrd["scikit_learn_version"]}', file=output_file)
    print(f'Start Timestamp: {lrd["start_timestamp"]}', file=output_file)
    print(f'End Timestamp: {lrd["end_timestamp"]}', file=output_file)
    print(f'Total Time: {lrd["total_time"]}', file=output_file)
    print("\n", file=output_file)

    for lrd in learner_result_dicts:
        print(f'Fold: {lrd["fold"]}', file=output_file)
        print(f'Model Parameters: {lrd.get("model_params", "")}', file=output_file)
        print(f'Grid Objective Score (Train) = {lrd.get("grid_score", "")}', file=output_file)
        if "result_table" in lrd:
            print(lrd["result_table"], file=output_file)
            print(f'Accuracy = {lrd["accuracy"]}', file=output_file)
        if "descriptive" in lrd:
            print("Descriptive statistics:", file=output_file)
            for desc_stat in ["min", "max", "avg", "std"]:
                actual = lrd["descriptive"]["actual"][desc_stat]
                predicted = lrd["descriptive"]["predicted"][desc_stat]
                print(
                    f" {desc_stat.title()} = {actual:.4f} (actual), "
                    f"{predicted:.4f} (predicted)",
                    file=output_file,
                )
            print(f'Pearson = {lrd["pearson"]:f}', file=output_file)
        print(f'Objective Function Score (Test) = {lrd.get("score", "")}', file=output_file)

        # now print the additional metrics, if there were any
        if lrd["additional_scores"]:
            print("", file=output_file)
            print("Additional Evaluation Metrics (Test):", file=output_file)
            for metric, score in lrd["additional_scores"].items():
                score = "" if np.isnan(score) else score
                print(f" {metric} = {score}", file=output_file)
        print("", file=output_file)


def _write_learning_curve_file(result_json_paths: List[str], output_file: IO[str]) -> None:
    """
    Combine individual learning curve results JSON files into single TSV.

    Take a list of paths to individual learning curve results json files and
    write out a single TSV file with the learning curve data.

    Parameters
    ----------
    result_json_paths : List[str]
        list of paths to the individual result JSON files.
    output_file : IO[str]
        The file buffer to write to.
    """
    learner_result_dicts = []

    # Map from feature set names to all features in them
    logger = get_skll_logger("experiment")
    for json_path_str in result_json_paths:
        json_path = Path(json_path_str)
        if not json_path.exists():
            logger.error(
                f"JSON results file {json_path} not found. Skipping "
                "summary creation. You can manually create the "
                "summary file after the fact by using the "
                "summarize_results script."
            )
            return
        else:
            with open(json_path) as json_file:
                obj = json.load(json_file)
                learner_result_dicts.extend(obj)

    # Build and write header
    header = [
        "featureset_name",
        "learner_name",
        "metric",
        "train_set_name",
        "training_set_size",
        "train_score_mean",
        "test_score_mean",
        "fit_time_mean",
        "train_score_std",
        "test_score_std",
        "fit_time_std",
        "scikit_learn_version",
        "version",
    ]
    writer = csv.DictWriter(output_file, header, extrasaction="ignore", dialect=csv.excel_tab)
    writer.writeheader()

    # write out the fields we need for the learning curve file
    # specifically, we need to separate out the curve sizes
    # and scores into individual entries.
    for lrd in learner_result_dicts:
        training_set_sizes = lrd["computed_curve_train_sizes"]
        train_scores_means_by_size = lrd["learning_curve_train_scores_means"]
        test_scores_means_by_size = lrd["learning_curve_test_scores_means"]
        fit_times_means_by_size = lrd["learning_curve_fit_times_means"]
        train_scores_stds_by_size = lrd["learning_curve_train_scores_stds"]
        test_scores_stds_by_size = lrd["learning_curve_test_scores_stds"]
        fit_times_stds_by_size = lrd["learning_curve_fit_times_stds"]

        # rename `grid_objective` to `metric` since the latter name can be confusing
        lrd["metric"] = lrd["grid_objective"]

        for (
            size,
            train_score_mean,
            test_score_mean,
            fit_time_mean,
            train_score_std,
            test_score_std,
            fit_time_std,
        ) in zip(
            training_set_sizes,
            train_scores_means_by_size,
            test_scores_means_by_size,
            fit_times_means_by_size,
            train_scores_stds_by_size,
            test_scores_stds_by_size,
            fit_times_stds_by_size,
        ):
            lrd["training_set_size"] = size
            lrd["train_score_mean"] = train_score_mean
            lrd["test_score_mean"] = test_score_mean
            lrd["fit_time_mean"] = fit_time_mean
            lrd["train_score_std"] = train_score_std
            lrd["test_score_std"] = test_score_std
            lrd["fit_time_std"] = fit_time_std

            writer.writerow(lrd)

    output_file.flush()


def _write_skll_folds(skll_fold_ids: FoldMapping, skll_fold_ids_file: IO[str]) -> None:
    """
    Take a dictionary of id->test-fold-number and write it to a file.

    Parameters
    ----------
    skll_fold_ids : FoldMapping
        Dictionary with ids as keys and test-fold-numbers as values.
    skll_fold_ids_file : IO[str]
        An open file handler to write to.
    """
    f = csv.writer(skll_fold_ids_file)
    f.writerow(["id", "cv_test_fold"])
    for example_id in skll_fold_ids:
        f.writerow([example_id, skll_fold_ids[example_id]])

    skll_fold_ids_file.flush()


def _write_summary_file(result_json_paths: List[str], output_file: IO[str], ablation: int = 0):
    """
    Summarize individual result JSON files.

    Take a list of paths to individual result json files and return a single
    file that summarizes all of them.

    Parameters
    ----------
    result_json_paths : List[str]
        A list of paths to the individual result JSON files.
    output_file : IO[str]
        The file buffer to write to.
    ablation : int, default=0
        The number of features to remove when doing ablation experiment.
    """
    learner_result_dicts = []
    # Map from feature set names to all features in them
    all_features = defaultdict(set)
    logger = get_skll_logger("experiment")
    yaml = YAML(typ="safe", pure=True)

    for json_path_str in result_json_paths:
        json_path = Path(json_path_str)
        if not json_path.exists():
            logger.error(
                f"JSON results file {json_path} not found. Skipping "
                "summary creation. You can manually create the "
                "summary file after the fact by using the "
                "summarize_results script."
            )
            return
        else:
            with open(json_path) as json_file:
                obj = json.load(json_file)
                featureset_name = obj[0]["featureset_name"]
                if ablation != 0 and "_minus_" in featureset_name:
                    parent_set = featureset_name.split("_minus_", 1)[0]
                    all_features[parent_set].update(yaml.load(obj[0]["featureset"]))
                learner_result_dicts.extend(obj)

    # Build and write header
    unique_columns = set(learner_result_dicts[0].keys()) - {"result_table", "descriptive"}
    if ablation != 0:
        unique_columns.add("ablated_features")
    header = sorted(unique_columns)
    writer = csv.DictWriter(output_file, header, extrasaction="ignore", dialect=csv.excel_tab)
    writer.writeheader()

    # Build "ablated_features" list and fix some backward compatible things
    for lrd in learner_result_dicts:
        featureset_name = lrd["featureset_name"]
        if ablation != 0:
            parent_set = featureset_name.split("_minus_", 1)[0]
            ablated_features = all_features[parent_set].difference(yaml.load(lrd["featureset"]))
            lrd["ablated_features"] = ""
            if ablated_features:
                lrd["ablated_features"] = json.dumps(sorted(ablated_features))

        # write out the new learner dict with the readable fields
        writer.writerow(lrd)

    output_file.flush()
