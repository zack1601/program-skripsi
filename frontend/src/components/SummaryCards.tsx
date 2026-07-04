import React from 'react';
import { Users, Activity, AlertCircle, Zap, Power, Shield } from 'lucide-react';

interface SummaryCardsProps {
  stats: {
    total: number;
    online: number;
    los: number;
    badRx: number;
    dying: number;
    suspend: number;
  };
}

const SummaryCards: React.FC<SummaryCardsProps> = ({ stats }) => {
  const cards = [
    { label: 'Total User', value: stats.total, icon: <Users size={16} />, accent: 'border-blue-500' },
    { label: 'Online', value: stats.online, icon: <Activity size={16} />, accent: 'border-green-500' },
    { label: 'LOS', value: stats.los, icon: <AlertCircle size={16} />, accent: 'border-red-500' },
    { label: 'BadRx', value: stats.badRx, icon: <Zap size={16} />, accent: 'border-orange-500' },
    { label: 'Dyinggasp', value: stats.dying, icon: <Power size={16} />, accent: 'border-purple-500' },
    { label: 'Suspend', value: stats.suspend, icon: <Shield size={16} />, accent: 'border-blue-400' },
  ];

  return (
    <div className="grid grid-cols-6 gap-4 mb-8">
      {cards.map((card) => (
        <div 
          key={card.label} 
          className={`bg-[#161B22] border-t-2 ${card.accent} p-4 rounded-xl shadow-2xl relative overflow-hidden group hover:translate-y-[-4px] transition-all duration-300`}
        >
          <div className="flex justify-between items-start mb-2">
            <span className="text-[10px] font-black text-white uppercase tracking-[0.2em]">{card.label}</span>
            <div className="opacity-20 group-hover:opacity-100 transition-opacity text-white">
              {card.icon}
            </div>
          </div>
          <div className="text-3xl font-black text-white tracking-tighter">
            {card.value.toLocaleString()}
          </div>
          {/* Subtle Glow Background */}
          <div className={`absolute -right-4 -bottom-4 w-12 h-12 rounded-full opacity-5 blur-2xl ${card.accent.replace('border-', 'bg-')}`}></div>
        </div>
      ))}
    </div>
  );
};

export default SummaryCards;
