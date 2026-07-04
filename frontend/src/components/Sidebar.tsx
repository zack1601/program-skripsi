import React from 'react';
import { Search, Rocket, Zap, AlertCircle, Shield, List, Activity, Settings } from 'lucide-react';

interface SidebarProps {
  onStart: () => void;
  isScanning: boolean;
  setFilter: (f: string) => void;
  currentFilter: string;
  search: string;
  setSearch: (s: string) => void;
}

const Sidebar: React.FC<SidebarProps> = ({ onStart, isScanning, setFilter, currentFilter, search, setSearch }) => {
  const filters = [
    { label: 'All', color: 'bg-slate-700' },
    { label: 'Online', color: 'bg-green-600' },
    { label: 'LOS', color: 'bg-red-600' },
    { label: 'BadRx', color: 'bg-orange-600' },
    { label: 'Dyinggasp', color: 'bg-purple-600' },
    { label: 'Suspend', color: 'bg-blue-600' },
  ];

  return (
    <aside className="w-1/5 bg-[#0A0D12] border-r border-[#1F242D] p-5 flex flex-col gap-8">
      {/* Brand Header */}
      <div className="flex items-center gap-2 mb-2">
        <div className="w-3 h-3 bg-enterprise-cyan rounded-full shadow-[0_0_10px_#00E5FF]"></div>
        <h1 className="text-lg font-black text-[#00E5FF] tracking-widest uppercase">NOC ENTERPRISE</h1>
      </div>

      {/* Network Search */}
      <div className="flex flex-col gap-3">
        <label className="text-[10px] font-black text-slate-500 uppercase tracking-[0.2em]">Network Search</label>
        <div className="relative">
          <input 
            type="text" 
            placeholder="SN / Name / ID..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full bg-[#11141B] border border-[#30363D] rounded-xl py-3 px-4 text-sm text-white placeholder:text-slate-600 focus:outline-none focus:border-enterprise-cyan transition-all"
          />
          <Search className="absolute right-4 top-1/2 -translate-y-1/2 text-slate-600" size={16} />
        </div>
      </div>

      {/* Status Filters */}
      <div className="flex flex-col gap-4">
        <label className="text-[10px] font-black text-slate-500 uppercase tracking-[0.2em]">Status Filters</label>
        <div className="flex flex-wrap gap-2">
          {filters.map((f) => (
            <button
              key={f.label}
              onClick={() => setFilter(f.label)}
              className={`px-4 py-2 rounded-full text-[11px] font-bold transition-all duration-200 border-2 ${
                currentFilter === f.label 
                ? `${f.color} border-white text-white shadow-lg scale-105` 
                : `bg-[#161B22] border-[#30363D] text-slate-400 hover:border-slate-500`
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {/* System Stats Mockup */}
      <div className="mt-auto flex flex-col gap-6">
        <button
          onClick={onStart}
          disabled={isScanning}
          className={`w-full flex items-center justify-center gap-3 py-4 rounded-xl font-black text-sm uppercase tracking-widest transition-all shadow-xl ${
            isScanning 
            ? 'bg-slate-800 text-slate-500 cursor-not-allowed' 
            : 'bg-gradient-to-r from-[#2563EB] to-[#00E5FF] hover:brightness-110 active:scale-95 text-white'
          }`}
        >
          <Rocket size={18} />
          {isScanning ? 'SCANNING...' : '🚀 RUN SCANNING'}
        </button>

        <div className="bg-[#11141B] border border-[#1F242D] p-4 rounded-xl">
          <div className="flex justify-between items-center mb-2">
            <span className="text-[9px] font-bold text-slate-500 uppercase tracking-widest">System Status</span>
            <span className="text-[9px] font-bold text-[#00E5FF] uppercase">Stable</span>
          </div>
          <div className="w-full bg-[#0E1117] h-1.5 rounded-full overflow-hidden">
            <div className="bg-[#00E676] h-full w-[85%] shadow-[0_0_10px_#00E676]"></div>
          </div>
          <div className="mt-4 text-center">
            <p className="text-[9px] text-slate-700 font-bold tracking-widest uppercase">Admin Access • v1.2.0</p>
          </div>
        </div>
      </div>
    </aside>
  );
};

export default Sidebar;
