import numpy as np
import pandas as pd

def calibrate_threshold_from_scores(
    scores_df: pd.DataFrame,
    distance_col: str = "distance",
    label_col: str = "is_genuine",
    target_far: float = 0.001,
):
    """
    scores_df:
      - distance: menor = más parecido
      - is_genuine: 1 si misma persona, 0 si impostor
    """
    if scores_df.empty:
        raise ValueError("No hay scores para calibrar.")

    impostor = scores_df[scores_df[label_col] == 0][distance_col].dropna().values
    genuine = scores_df[scores_df[label_col] == 1][distance_col].dropna().values

    if len(impostor) == 0 or len(genuine) == 0:
        raise ValueError("Se requieren scores genuinos e impostores.")

    thresholds = np.unique(np.round(scores_df[distance_col].dropna().values, 6))
    rows = []

    for thr in thresholds:
        far = float(np.mean(impostor <= thr))
        fnr = float(np.mean(genuine > thr))
        rows.append({"threshold": float(thr), "far": far, "fnr": fnr})

    curve = pd.DataFrame(rows).sort_values("threshold")
    eligible = curve[curve["far"] <= target_far]

    if eligible.empty:
        best = curve.iloc[0].to_dict()
    else:
        # entre los que cumplen FAR, escoger el de menor FNR
        best = eligible.sort_values(["fnr", "threshold"]).iloc[0].to_dict()

    return {
        "recommended_threshold": float(best["threshold"]),
        "far_observed": float(best["far"]),
        "fnr_observed": float(best["fnr"]),
        "curve": curve,
    }