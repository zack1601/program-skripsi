import React from 'react';
import { ONTData } from '../App';

interface ONTTableProps {
  data: ONTData[];
}

const ONTTable: React.FC<ONTTableProps> = ({ data }) => {
  return (
    <div className="overflow-x-auto max-h-[600px] rounded-xl">
      <table className="w-full text-left border-collapse bg-[#161B22]">
        <thead className="sticky top-0 bg-[#1C2128] z-20 shadow-xl">
          <tr className="border-b border-[#30363D]">
            <th className="px-5 py-4 text-[#00E5FF] text-[10px] font-black uppercase tracking-widest">OLT</th>
            <th className="px-5 py-4 text-[#00E5FF] text-[10px] font-black uppercase tracking-widest">Nama / ID</th>
            <th className="px-5 py-4 text-[#00E5FF] text-[10px] font-black uppercase tracking-widest">Port</th>
            <th className="px-5 py-4 text-[#00E5FF] text-[10px] font-black uppercase tracking-widest">Serial Number</th>
            <th className="px-5 py-4 text-[#00E5FF] text-[10px] font-black uppercase tracking-widest">Status</th>
            <th className="px-5 py-4 text-[#00E5FF] text-[10px] font-black uppercase tracking-widest">Power / Cause</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-[#30363D]/50">
          {data.length === 0 ? (
            <tr>
              <td colSpan={6} className="px-5 py-24 text-center text-slate-600 font-bold italic tracking-widest text-sm">
                No data available. Click 'RUN SCANNING' to begin.
              </td>
            </tr>
          ) : (
            data.map((row, idx) => {
              const isLos = row.power_cause === 'LOS';
              const isBadRx = row.power_cause === 'BadRx';
              const isSuspend = row.power_cause === 'Suspend';

              return (
                <tr 
                  key={idx} 
                  className={`transition-colors duration-150 ${
                    isLos ? 'bg-red-500/10 hover:bg-red-500/20' : 
                    isBadRx ? 'bg-orange-500/10 hover:bg-orange-500/20' :
                    isSuspend ? 'bg-slate-700/10 hover:bg-slate-700/20' : 
                    'hover:bg-[#1C2128]'
                  }`}
                >
                  <td className="px-5 py-4 text-[11px] font-mono text-slate-400">{row.olt}</td>
                  <td className="px-5 py-4 text-[11px] font-bold text-white tracking-tight">{row.customer}</td>
                  <td className="px-5 py-4 text-[11px] font-mono text-slate-400">{row.port}</td>
                  <td className="px-5 py-4 text-[11px] font-mono text-slate-400">{row.sn}</td>
                  <td className="px-5 py-4">
                    <span className={`px-2.5 py-1 rounded-md text-[9px] font-black uppercase ${
                      row.status === 'Online' ? 'bg-green-600 text-white' : 'bg-red-600 text-white'
                    }`}>
                      {row.status}
                    </span>
                  </td>
                  <td className="px-5 py-4 text-[11px] font-black">
                    <span className={
                      isLos ? 'text-red-500 animate-pulse' :
                      isBadRx ? 'text-orange-500' :
                      isSuspend ? 'text-blue-400' :
                      row.status === 'Online' ? 'text-[#00E5FF]' : 'text-slate-400'
                    }>
                      {row.power_cause}
                    </span>
                  </td>
                </tr>
              );
            })
          )}
        </tbody>
      </table>
    </div>
  );
};

export default ONTTable;
