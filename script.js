/**
 * NETWATCH OPS CENTER - JavaScript Engine
 * Handles Real-time DOM manipulations
 */

// Function to auto-scroll the streaming table to the latest row
function autoScrollTable() {
    const tableContainers = document.querySelectorAll('[data-testid="stDataFrame"]');
    tableContainers.forEach(container => {
        // Search for the scrollable container within Streamlit's shadow DOM / internal divs
        const scrollable = container.querySelector('div[class*="st-emotion-cache-"]');
        if (scrollable && scrollable.scrollHeight > scrollable.clientHeight) {
            scrollable.scrollTop = scrollable.scrollHeight;
        }
    });
}

// Observe DOM changes to trigger auto-scroll during data streaming
const observer = new MutationObserver((mutations) => {
    // Only scroll if a new row was added to a table
    autoScrollTable();
});

// Initialize observer once the document is ready
document.addEventListener('DOMContentLoaded', () => {
    observer.observe(document.body, { 
        childList: true, 
        subtree: true 
    });
});

// Fallback for Streamlit re-renders
setInterval(autoScrollTable, 1000);
