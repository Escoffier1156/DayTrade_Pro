import { createChart, IChartApi, ISeriesApi, LineStyle, CrosshairMode, ColorType, AreaSeries, createSeriesMarkers } from 'lightweight-charts';
import type { Target } from './types';

export class TargetChart {
  private chart: IChartApi;
  private areaSeries: ISeriesApi<"Area">;
  private markersPrimitive: any = null;

  constructor(container: HTMLElement) {
    const chartOptions = {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: '#d1d5db',
      },
      grid: {
        vertLines: { color: 'rgba(255, 255, 255, 0.05)' },
        horzLines: { color: 'rgba(255, 255, 255, 0.05)' },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
      },
      rightPriceScale: {
        borderColor: '#1a2a40',
        autoScale: true,
      },
      timeScale: {
        borderColor: '#1a2a40',
        timeVisible: true,
        secondsVisible: false,
      },
    };

    this.chart = createChart(container, chartOptions);

    this.areaSeries = this.chart.addSeries(AreaSeries, {
      lineColor: '#f59e0b', // Amber line for terminal look
      topColor: 'rgba(245, 158, 11, 0.3)',
      bottomColor: 'rgba(245, 158, 11, 0.0)',
      lineWidth: 2,
    });
  }

  public setData(target: Target) {
    if (target.history && target.history.length > 0) {
      const jstHistory = target.history.map(p => ({
        time: p.time + 32400, // UTC+9 (JST)
        value: p.value
      }));
      // @ts-ignore
      this.areaSeries.setData(jstHistory);
      
      // Add markers
      const markers: any[] = [];
      const firstPoint = jstHistory[0];
      
      // Entry Marker
      markers.push({
        time: firstPoint.time,
        position: 'belowBar',
        color: '#3b82f6',
        shape: 'circle',
        text: `Buy @ ¥${target.entry_price}`
      });
      
      // Exit Marker (if closed)
      if (target.status !== 'OPEN') {
        const lastPoint = jstHistory[jstHistory.length - 1];
        const isWin = target.status === 'HIT_TP';
        markers.push({
          time: lastPoint.time,
          position: 'aboveBar',
          color: isWin ? '#10b981' : '#ef4444',
          shape: 'circle',
          text: `${isWin ? 'TP' : 'SL'} @ ¥${lastPoint.value}`
        });
      }
      
      
      if (this.markersPrimitive) {
        this.markersPrimitive.setMarkers(markers);
      } else {
        this.markersPrimitive = createSeriesMarkers(this.areaSeries, markers);
      }
      this.chart.timeScale().fitContent();
    }
  }

  public addPriceLines(target: Target) {
    this.areaSeries.createPriceLine({
      price: target.target,
      color: '#10b981', // Green for TP
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      axisLabelVisible: true,
      title: 'TP',
    });

    this.areaSeries.createPriceLine({
      price: target.stop,
      color: '#ef4444', // Red for SL
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      axisLabelVisible: true,
      title: 'SL',
    });
    
    this.areaSeries.createPriceLine({
      price: target.entry_price,
      color: '#d1d5db', // Gray for Entry
      lineWidth: 1,
      lineStyle: LineStyle.Dotted,
      axisLabelVisible: true,
      title: 'Entry',
    });
  }

  public resize(width: number, height: number) {
    this.chart.resize(width, height);
  }

  public remove() {
    this.chart.remove();
  }
}
