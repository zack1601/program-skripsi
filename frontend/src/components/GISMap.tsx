import React from 'react';
import { MapContainer, TileLayer, Marker, Popup } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { ONTData } from '../App';

interface GISMapProps {
  data: ONTData[];
}

const GISMap: React.FC<GISMapProps> = ({ data }) => {
  const center: [number, number] = [-6.2088, 106.8456];

  const createPulseIcon = (type: string) => {
    const className = type === 'LOS' ? 'marker-los' : 'marker-bad-rx';
    return L.divIcon({
      className: 'custom-pulse-icon',
      html: `<div class="${className}"></div>`,
      iconSize: [20, 20],
      iconAnchor: [10, 10],
    });
  };

  const createNormalIcon = (status: string) => {
    const color = status === 'Online' ? '#00E676' : '#8B949E';
    return L.divIcon({
      className: 'custom-dot-icon',
      html: `<div style="background-color: ${color}; width: 10px; height: 10px; border-radius: 50%; border: 2px solid white; box-shadow: 0 0 5px rgba(0,0,0,0.5);"></div>`,
      iconSize: [10, 10],
      iconAnchor: [5, 5],
    });
  };

  return (
    <div className="h-[400px] w-full bg-[#0E1117] border-2 border-[#1F242D] rounded-xl overflow-hidden shadow-inner relative group">
      <MapContainer 
        center={center} 
        zoom={11} 
        scrollWheelZoom={true} 
        style={{ height: '100%', width: '100%' }}
      >
        <TileLayer
          attribution='&copy; CARTO'
          url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
        />
        
        {data.map((node, idx) => {
          let icon;
          if (node.power_cause === 'LOS') icon = createPulseIcon('LOS');
          else if (node.power_cause === 'BadRx') icon = createPulseIcon('BadRx');
          else icon = createNormalIcon(node.status);

          return (
            <Marker key={idx} position={[node.lat, node.lon]} icon={icon}>
              <Popup className="enterprise-popup">
                <div className="p-1 min-w-[150px]">
                  <p className="font-black text-xs text-slate-800 border-b pb-1 mb-1">{node.customer}</p>
                  <p className="text-[10px] text-slate-600 font-bold">SN: {node.sn}</p>
                  <p className="text-[10px] font-black uppercase mt-1" style={{color: node.status === 'Online' ? '#22C55E' : '#EF4444'}}>
                    STATUS: {node.status}
                  </p>
                  <p className="text-[10px] font-black text-slate-800 uppercase">CAUSE: {node.power_cause}</p>
                </div>
              </Popup>
            </Marker>
          );
        })}
      </MapContainer>

      {/* Map Legend Overlay */}
      <div className="absolute bottom-4 left-4 bg-[#161B22]/90 border border-[#30363D] p-3 rounded-lg z-[1000] flex gap-4 backdrop-blur-sm shadow-2xl">
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 bg-[#FF4D4D] rounded-full animate-pulse shadow-[0_0_8px_#FF4D4D]"></div>
          <span className="text-[9px] font-black text-white uppercase tracking-widest">LOS ACTIVE</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 bg-[#FFA500] rounded-full animate-pulse shadow-[0_0_8px_#FFA500]"></div>
          <span className="text-[9px] font-black text-white uppercase tracking-widest">BADRX ALERT</span>
        </div>
      </div>
    </div>
  );
};

export default GISMap;
