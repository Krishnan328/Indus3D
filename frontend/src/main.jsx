import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import './index.css'

// Patch fetch globally to include credentials (session cookies) on every
// request. Required for Flask session auth to work cross-origin.
const _originalFetch = window.fetch;
window.fetch = async (url, opts = {}) => {
  if (url instanceof Request) return _originalFetch(url, opts);

  const res = await _originalFetch(url, { ...opts, credentials: "include" });
  if (res.status === 429) {
    window.dispatchEvent(new CustomEvent("api-throttled"));
    // Implement a simple sleep to artificially back-off
    await new Promise(resolve => setTimeout(resolve, 2000));
  }
  return res;
};

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, info) {
    console.error("React Error Boundary caught an error:", error, info);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex flex-col items-center justify-center h-screen w-full bg-black text-red-400 font-mono p-10 text-center">
          <h1 className="text-2xl font-bold mb-4">Something went wrong</h1>
          <p className="opacity-70 mb-8">The dashboard encountered an unexpected error.</p>
          <pre className="text-left text-xs bg-gray-900 p-4 rounded-lg overflow-auto max-w-4xl w-full border border-gray-800">
            {this.state.error?.stack}
          </pre>
          <button
            onClick={() => window.location.reload()}
            className="mt-8 px-6 py-2 bg-red-900 hover:bg-red-800 text-white rounded font-bold"
          >
            Reload Dashboard
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>,
)
// Force Vite full reload
