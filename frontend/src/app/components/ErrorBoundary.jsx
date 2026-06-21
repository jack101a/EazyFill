import React from "react";
import PropTypes from "prop-types";
import { AlertTriangle, RefreshCw } from "lucide-react";

export class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, info) {
    console.error("Dashboard error:", error, info);
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null });
    window.location.reload();
  };

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen bg-[#020617] flex items-center justify-center p-8">
          <div className="bg-white/[0.02] backdrop-blur-2xl border border-white/[0.05] rounded-2xl p-8 max-w-md text-center space-y-4">
            <div className="p-3 bg-rose-500/20 text-rose-400 rounded-xl inline-flex">
              <AlertTriangle size={32} />
            </div>
            <h2 className="text-xl font-bold text-white">Something went wrong</h2>
            <p className="text-sm text-slate-400">
              {this.state.error?.message || "An unexpected error occurred."}
            </p>
            <button
              onClick={this.handleReset}
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-indigo-500 hover:bg-indigo-400 text-white font-medium text-sm transition-all shadow-lg shadow-indigo-500/30"
            >
              <RefreshCw size={16} /> Reset Dashboard
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

ErrorBoundary.propTypes = {
  children: PropTypes.node.isRequired,
};