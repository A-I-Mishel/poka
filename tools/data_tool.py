from langchain.tools import tool
import pandas as pd

from services.context import get_current_user_id
from services.files import FileStore
from services.limits import MAX_CSV_ROWS


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
    user_id = get_current_user_id()
    if not user_id:
        return "STATUS=INVALID tool=analyze_csv: no user context, cannot resolve uploads."
    path = FileStore(user_id).resolve_upload(upload_id)
    if path is None:
        return "STATUS=DENIED tool=analyze_csv: unknown upload ID or not owned by you."
    try:
        df: pd.DataFrame = pd.read_csv(str(path), nrows=MAX_CSV_ROWS + 1)
        truncated = len(df) > MAX_CSV_ROWS
        if truncated:
            df = df.iloc[:MAX_CSV_ROWS]
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
