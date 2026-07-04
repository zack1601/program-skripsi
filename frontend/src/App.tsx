import React, { useState, useEffect, useMemo } from 'react';
import Sidebar from './components/Sidebar';
import SummaryCards from './components/SummaryCards';
import GISMap from './components/GISMap';
import ONTTable from './components/ONTTable';

// Ensure CSS is imported
import './index.css';

export interface ONTData {
  olt: string;
  customer: string;
  port: string;
  sn: string;
  status: string;
  rx_power: string;
  last_down_cause: string;
  power_cause: string;
  lat: number;
  lon: number;
}

const App: React.FC = () => {
  const [data, setData] = useState<ONTData[]>([]);
  const [isScanning, setIsScanning] = useState(false);
  const [filter, setFilter] = useState('All');
  const [search, setSearch] = useState('');

  const startAudit = async () => {
    setIsScanning(true);
    setData([]);
    
    try {
      const response = await fetch('http://localhost:8000/api/scan');
      if (!response.body) return;

      const reader = response.body.getReader();
      const decoder = new TextDecoder();

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value);
        const lines = chunk.split('\n');

        lines.forEach(line => {
          if (!line.trim()) return;
          try {
            const message = JSON.parse(line);
            if (message.type === 'data') {
              setData(prev => [...prev, message.payload]);
            } else if (message.type === 'done') {
              setIsScanning(false);
            }
          } catch (e) {
            console.error("Stream parse error:", e);
          }
        });
      }
    } catch (error) {
      console.error("Scan error:", error);
      setIsScanning(false);
    }
  };

  const filteredData = useMemo(() => {
    return data.filter(item => {
      const matchesFilter = filter === 'All' || item.power_cause === filter || item.status === filter;
      const matchesSearch = 
        item.customer.toLowerCase().includes(search.toLowerCase()) ||
        item.sn.toLowerCase().includes(search.toLowerCase());
      return matchesFilter && matchesSearch;
    });
  }, [data, filter, search]);

  const stats = useMemo(() => ({
    total: data.length,
    online: data.filter(d => d.status === 'Online').length,
    los: data.filter(d => d.power_cause === 'LOS').length,
    badRx: data.filter(d => d.power_cause === 'BadRx').length,
    dying: data.filter(d => d.power_cause === 'Dyinggasp').length,
    suspend: data.filter(d => d.power_cause === 'Suspend').length,
  }), [data]);

  return (
    <div className="flex h-screen bg-[#0E1117] text-white overflow-hidden">
      {/* Sidebar - Fix Width & Color */}
      <Sidebar 
        onStart={startAudit} 
        isScanning={isScanning} 
        setFilter={setFilter} 
        currentFilter={filter}
        search={search}
        setSearch={setSearch}
      />

      {/* Main Content Area */}
      <main className="flex-1 flex flex-col p-8 overflow-y-auto bg-[#0E1117]">
        {/* Top Header Summary */}
        <SummaryCards stats={stats} />
        
        <div className="mt-8 space-y-8">
          {/* GIS Map Section */}
          <section className="bg-[#161B22] border border-[#30363D] rounded-2xl overflow-hidden shadow-2xl">
            <div className="px-6 py-4 border-b border-[#30363D] bg-black/20 flex justify-between items-center">
              <h2 className="text-[#00E5FF] font-black uppercase tracking-widest text-sm">🌍 Network GIS Awareness</h2>
              <span className="text-[10px] text-slate-500 font-bold uppercase italic">CartoDB Dark Theme</span>
            </div>
            <div className="p-2">
               <GISMap data={filteredData} />
            </div>
          </section>

          {/* Monitoring Table Section */}
          <section className="bg-[#161B22] border border-[#30363D] rounded-2xl shadow-2xl overflow-hidden">
             <div className="px-6 py-4 border-b border-[#30363D] bg-black/20 flex justify-between items-center">
              <h2 className="text-[#00E5FF] font-black uppercase tracking-widest text-sm">📋 Live Node Monitoring</h2>
              <div className="flex items-center gap-3">
                <span className="text-[10px] text-white font-black bg-[#00E5FF]/20 px-3 py-1 rounded-full border border-[#00E5FF]/30">
                  {filteredData.length} NODES
                </span>
              </div>
            </div>
            <ONTTable data={filteredData} />
          </section>
        </div>
      </main>
    </div>
  );
};

export default App;
