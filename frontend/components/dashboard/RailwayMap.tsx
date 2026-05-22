'use client';

import React from 'react';
import { MapContainer, TileLayer, GeoJSON, Marker, Popup } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import L from 'leaflet';

// Fix icon issue in react-leaflet on Next.js
delete (L.Icon.Default.prototype as any)._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon-2x.png',
  iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-shadow.png',
});

interface RailwayMapProps {
  lat: number;
  lng: number;
  geoData?: any; // GeoJSON dari backend
}

const RailwayMap: React.FC<RailwayMapProps> = ({ lat, lng, geoData }) => {
  const position: [number, number] = [lat, lng];

  const geoJsonStyle = () => {
    return {
      color: '#ff2d55', // Red line alert state
      weight: 5,
      opacity: 0.8,
    };
  };

  return (
    <div style={{ height: '400px', width: '100%', borderRadius: '12px', overflow: 'hidden' }}>
      <MapContainer center={position} zoom={15} style={{ height: '100%', width: '100%' }}>
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <Marker position={position}>
          <Popup>
            Lokasi Anomali Terdeteksi.
          </Popup>
        </Marker>
        {geoData && (
          <GeoJSON data={geoData} style={geoJsonStyle} />
        )}
      </MapContainer>
    </div>
  );
};

export default RailwayMap;
