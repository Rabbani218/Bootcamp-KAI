'use client';

import React from 'react';

interface LogoProps {
  size?: 'sm' | 'md' | 'lg';
  variant?: 'horizontal' | 'icon-only';
  showText?: boolean;
}

export function LogoBrand({ 
  size = 'md', 
  variant = 'horizontal',
  showText = true 
}: LogoProps) {
  const sizeMap = {
    sm: 'w-6 h-6',
    md: 'w-8 h-8',
    lg: 'w-12 h-12',
  };

  const textSizeMap = {
    sm: 'text-xs',
    md: 'text-sm',
    lg: 'text-lg',
  };

  if (variant === 'icon-only') {
    return (
      <div className={`${sizeMap[size]} flex items-center justify-center bg-gradient-to-br from-blue-600 to-orange-500 rounded-lg shadow-lg drop-shadow-[0_0_12px_rgba(34,197,94,0.4)]`}>
        <img 
          src="/Logo-KAI.png" 
          alt="KAI" 
          className="w-full h-full object-contain p-0.5" 
        />
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2.5">
      <div className={`${sizeMap[size]} flex items-center justify-center bg-gradient-to-br from-blue-600 to-orange-500 rounded-lg shadow-lg drop-shadow-[0_0_12px_rgba(34,197,94,0.4)]`}>
        <img 
          src="/Logo-KAI.png" 
          alt="KAI" 
          className="w-full h-full object-contain p-0.5" 
        />
      </div>
      {showText && (
        <div>
          <div className={`${textSizeMap[size]} font-black tracking-wide text-white`}>
            NusaRail <span className="text-neon-cyan">Vision</span>
          </div>
          <div className="text-[10px] text-slate-500 leading-none">
            Traffic Anomaly Detection
          </div>
        </div>
      )}
    </div>
  );
}
