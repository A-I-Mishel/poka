from langchain.tools import tool
import pandas as pd


@tool
def analyze_csv(file_path: str) -> str:
    """Analyze a CSV file and return basic statistics.

    Args:
        file_path: Local path to the CSV file.

    Returns:
        Row/column counts, column names, numeric summary, and missing values.
    """
    try:
        df: pd.DataFrame = pd.read_csv(file_path)
        numeric = df.select_dtypes(include="number")
        summary: str = f"Rows: {len(df)}, Columns: {len(df.columns)}\n"
        summary += f"Column names: {', '.join(df.columns.tolist())}\n"
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
        return f"Error analyzing CSV: {str(e)}"
