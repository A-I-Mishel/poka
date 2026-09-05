from langchain.tools import tool
import pandas as pd
from typing import Any, Dict, List, Optional, Tuple

from services.context import get_current_user_id
from services.files import FileStore
from services.limits import MAX_CSV_ROWS

_CSV_OPS = (
    "overview", "describe", "missing", "unique", "groupby",
    "correlation", "filter", "head", "outliers",
)
_CSV_OUT_CHARS = 4000


def _cap_output(text: str) -> str:
    """Cap tool output length so one result cannot flood context."""
    if len(text) > _CSV_OUT_CHARS:
        return text[:_CSV_OUT_CHARS] + "\n[Note: output truncated.]"
    return text


def _load_csv_frame(upload_id: str) -> Tuple[Optional[pd.DataFrame], Optional[str], bool]:
    """Resolve + load a capped frame. Returns (df, error, truncated)."""
    user_id = get_current_user_id()
    if not user_id:
        return None, "STATUS=INVALID tool=csv: no user context, cannot resolve uploads.", False
    path = FileStore(user_id).resolve_upload(upload_id)
    if path is None:
        return None, "STATUS=DENIED tool=csv: unknown upload ID or not owned by you.", False
    frame: Optional[pd.DataFrame] = None
    last_error: str = ""
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            frame = pd.read_csv(
                str(path),
                nrows=MAX_CSV_ROWS + 1,
                encoding=encoding,
                on_bad_lines="skip",
            )
            break
        except UnicodeDecodeError as e:
            last_error = str(e)[:120]
            continue
        except Exception as e:
            return None, f"STATUS=FAILED tool=csv: {str(e)[:200]}", False
    if frame is None:
        return None, f"STATUS=FAILED tool=csv: unreadable encoding. {last_error}", False
    truncated = len(frame) > MAX_CSV_ROWS
    if truncated:
        frame = frame.iloc[:MAX_CSV_ROWS]
    return frame, None, truncated


@tool
def analyze_csv(upload_id: str) -> str:
    """Analyze an uploaded CSV by its upload ID and return statistics.

    Use ONLY with an upload ID the user actually provided in this
    conversation (from an attachment). Never invent IDs and never use
    filesystem paths — only opaque upload IDs are accepted.

    Args:
        upload_id: The 16-hex upload ID of a CSV owned by the user.

    Returns:
        Row/column counts, numeric summary, and missing values, or a
        STATUS= error marker on failure.
    """
    try:
        df, error, truncated = _load_csv_frame(upload_id)
        if error is not None:
            return error
        assert df is not None
        numeric = df.select_dtypes(include="number")
        summary: str = f"Rows analyzed: {len(df)}, Columns: {len(df.columns)}\n"
        summary += f"Column names: {', '.join(df.columns.tolist())}\n"
        if truncated:
            summary += f"\n[Note: analysis limited to the first {MAX_CSV_ROWS} rows.]\n"
        if not numeric.empty:
            summary += "\nNumeric Summary:\n"
            summary += numeric.describe().to_string()
        else:
            summary += "\nNo numeric columns found."
        missing = df.isnull().sum()
        if missing.any():
            summary += "\n\nMissing values per column:\n"
            summary += missing[missing > 0].to_string()
        return summary
    except Exception as e:
        return f"STATUS=FAILED tool=analyze_csv: {str(e)[:200]}"


def _require_column(df: pd.DataFrame, column: str) -> Optional[str]:
    """Validate a column name; return an error string or None."""
    if not column:
        return "STATUS=INVALID tool=csv_inspect: this operation needs a column name."
    if column not in df.columns:
        return (
            f"STATUS=INVALID tool=csv_inspect: unknown column '{column}'. "
            f"Available: {', '.join(df.columns.tolist()[:20])}"
        )
    return None


@tool
def csv_inspect(upload_id: str, operation: str, column: str = "", params: str = "") -> str:
    """Run one controlled analysis operation on an uploaded CSV.

    No arbitrary code runs: only the whitelisted operations below execute,
    always on a row-capped frame with truncated output.

    Operations:
    - overview: shape, columns, dtypes, first rows
    - describe: numeric statistics
    - missing: per-column missing counts and share
    - unique: distinct counts + top values (needs column)
    - groupby: group sizes, optional mean of a numeric column.
      params: "group_col" or "group_col,agg_col"
    - correlation: numeric correlation matrix (max 12 columns)
    - filter: first matching rows. params: "col,op,value" with op one of
      =, !=, >, <, >=, <=, contains
    - head: first N rows. params: N (1-50, default 5)
    - outliers: IQR-based outlier counts per numeric column

    Args:
        upload_id: The 16-hex upload ID of a CSV owned by the user.
        operation: One of the operations listed above.
        column: Target column for unique/filter operations.
        params: Operation-specific parameters (see above).

    Returns:
        The operation result text, or a STATUS= error marker.
    """
    op = str(operation or "").strip().lower()
    if op not in _CSV_OPS:
        return (
            f"STATUS=INVALID tool=csv_inspect: unknown operation '{operation}'. "
            f"Supported: {', '.join(_CSV_OPS)}."
        )
    try:
        df, error, truncated = _load_csv_frame(upload_id)
        if error is not None:
            return error
        assert df is not None
        note = f"\n[Note: limited to first {MAX_CSV_ROWS} rows.]" if truncated else ""

        if op == "overview":
            buf = [
                f"Shape: {len(df)} rows x {len(df.columns)} columns",
                "Columns: " + ", ".join(f"{c} ({df[c].dtype})" for c in df.columns),
                "",
                "First rows:",
                df.head(5).to_string(),
            ]
            return _cap_output("\n".join(buf) + note)

        if op == "describe":
            numeric = df.select_dtypes(include="number")
            if numeric.empty:
                return "STATUS=EMPTY tool=csv_inspect: no numeric columns to describe." + note
            return _cap_output("Numeric description:\n" + numeric.describe().to_string() + note)

        if op == "missing":
            missing = df.isnull().sum()
            total = len(df) if len(df) else 1
            lines = [
                f"{c}: {int(v)} ({100.0 * int(v) / total:.1f}%)"
                for c, v in missing.items()
            ]
            return _cap_output("Missing values per column:\n" + "\n".join(lines) + note)

        if op == "unique":
            err = _require_column(df, column)
            if err:
                return err
            series = df[column].astype(str)
            top = series.value_counts().head(10)
            lines = [f"Distinct values in '{column}': {int(series.nunique())}", ""]
            lines += [f"{val}: {int(cnt)}" for val, cnt in top.items()]
            return _cap_output("\n".join(lines) + note)

        if op == "groupby":
            parts = [p.strip() for p in str(params).split(",") if p.strip()]
            if not parts:
                return "STATUS=INVALID tool=csv_inspect: groupby needs params 'group_col[,agg_col]'."
            err = _require_column(df, parts[0])
            if err:
                return err
            grouped = df.groupby(parts[0])
            if len(parts) > 1:
                agg_col = parts[1]
                err = _require_column(df, agg_col)
                if err:
                    return err
                values = pd.to_numeric(grouped[agg_col].mean(numeric_only=True), errors="coerce")
                table = values.head(20).to_string()
                return _cap_output(f"Mean of '{agg_col}' by '{parts[0]}' (top 20):\n{table}" + note)
            sizes = grouped.size().head(20)
            return _cap_output(f"Group sizes by '{parts[0]}' (top 20):\n{sizes.to_string()}" + note)

        if op == "correlation":
            numeric = df.select_dtypes(include="number")
            if numeric.shape[1] < 2:
                return "STATUS=EMPTY tool=csv_inspect: need at least 2 numeric columns." + note
            corr = numeric.iloc[:, :12].corr(numeric_only=True)
            return _cap_output("Correlation matrix:\n" + corr.to_string() + note)

        if op == "filter":
            err = _require_column(df, column)
            if err:
                return err
            bits = [p.strip() for p in str(params).split(",", 2)]
            if len(bits) != 3:
                return "STATUS=INVALID tool=csv_inspect: filter needs params 'col,op,value'."
            _, fop, raw_value = bits
            series = df[column]
            try:
                if fop == "contains":
                    mask = series.astype(str).str.contains(raw_value, case=False, na=False)
                else:
                    try:
                        value: Any = float(raw_value)
                        series = pd.to_numeric(series, errors="coerce")
                    except ValueError:
                        value = raw_value
                    if fop == "=":
                        mask = series == value
                    elif fop == "!=":
                        mask = series != value
                    elif fop == ">":
                        mask = series > value
                    elif fop == "<":
                        mask = series < value
                    elif fop == ">=":
                        mask = series >= value
                    elif fop == "<=":
                        mask = series <= value
                    else:
                        return "STATUS=INVALID tool=csv_inspect: op must be one of =, !=, >, <, >=, <=, contains."
            except Exception as e:
                return f"STATUS=FAILED tool=csv_inspect: filter failed ({str(e)[:120]})."
            matched = df[mask].head(10)
            return _cap_output(
                f"Matching rows: {int(mask.sum())} (showing up to 10):\n"
                + matched.to_string()
                + note
            )

        if op == "head":
            try:
                n = max(1, min(50, int(str(params or "5").strip())))
            except ValueError:
                return "STATUS=INVALID tool=csv_inspect: head params must be a number 1-50."
            return _cap_output(f"First {n} rows:\n" + df.head(n).to_string() + note)

        if op == "outliers":
            numeric = df.select_dtypes(include="number")
            if numeric.empty:
                return "STATUS=EMPTY tool=csv_inspect: no numeric columns to check." + note
            lines = []
            for col in numeric.columns[:12]:
                series = pd.to_numeric(numeric[col], errors="coerce").dropna()
                if len(series) < 4:
                    continue
                q1, q3 = series.quantile(0.25), series.quantile(0.75)
                iqr = q3 - q1
                lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
                count = int(((series < lo) | (series > hi)).sum())
                lines.append(f"{col}: {count} outliers (IQR range {lo:.3g}..{hi:.3g})")
            if not lines:
                return "STATUS=EMPTY tool=csv_inspect: not enough data for outlier check." + note
            return _cap_output("Outlier check (IQR method):\n" + "\n".join(lines) + note)

        return f"STATUS=INVALID tool=csv_inspect: unsupported operation '{op}'."
    except Exception as e:
        return f"STATUS=FAILED tool=csv_inspect: {str(e)[:200]}"
