import sqlite3
import pandas as pd
import os
import datetime

DB_PATH = "noc_database.db"

def get_connection():
    """Create and return a database connection."""
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    """Initialize the database (optional, as pandas to_sql creates tables automatically)"""
    # Just to ensure the DB file is created if it doesn't exist
    conn = get_connection()
    conn.close()

def save_scan_results(df):
    """
    Save the final dataframe to two SQLite tables:
    1. latest_scan: Overwritten every time (acts like the old CSV cache)
    2. scan_history: Appended with a timestamp for trending
    """
    if df.empty:
        return
        
    conn = get_connection()
    try:
        # Save to latest_scan (overwrite)
        df.to_sql('latest_scan', conn, if_exists='replace', index=False)
        
        # Prepare for history (add timestamp)
        df_history = df.copy()
        df_history['scan_timestamp'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Append to history
        df_history.to_sql('scan_history', conn, if_exists='append', index=False)
    except Exception as e:
        print(f"Error saving to database: {e}")
    finally:
        conn.close()

def load_latest_scan():
    """Load the most recent scan data from the database."""
    if not os.path.exists(DB_PATH):
        return pd.DataFrame()
        
    conn = get_connection()
    try:
        df = pd.read_sql_query("SELECT * FROM latest_scan", conn)
        return df
    except Exception as e:
        print(f"Error loading from database: {e}")
        return pd.DataFrame()
    finally:
        conn.close()

def get_historical_trend():
    """
    Get a summary of scan history for the line chart.
    Groups by scan_timestamp and Category to count occurrences.
    """
    if not os.path.exists(DB_PATH):
        return pd.DataFrame()
        
    conn = get_connection()
    try:
        # Simple query to get counts of each category per scan session
        query = """
        SELECT 
            scan_timestamp, 
            Category, 
            COUNT(*) as count 
        FROM scan_history 
        GROUP BY scan_timestamp, Category
        ORDER BY scan_timestamp ASC
        """
        df = pd.read_sql_query(query, conn)
        return df
    except Exception as e:
        print(f"Error loading historical trend: {e}")
        return pd.DataFrame()
    finally:
        conn.close()
