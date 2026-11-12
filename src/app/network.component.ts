import { AfterViewInit, Component, ElementRef, OnDestroy, ViewChild, effect, input, output } from '@angular/core';
import * as echarts from 'echarts/core';
import { GraphChart } from 'echarts/charts';
import { TooltipComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import { AGENTS } from './nexus.service';
echarts.use([GraphChart, TooltipComponent, CanvasRenderer]);

@Component({
  selector: 'nexus-network', standalone: true,
  template: '<div #chart class="network-canvas" role="img" aria-label="Interactive trust network: User Agent, Nexus, four design agents, Sentinel verifier and PayPal. Select an agent to inspect its reputation."></div>',
  styles: [':host {display:block;width:100%;height:100%;min-height:290px} .network-canvas{width:100%;height:100%;min-height:290px}']
})
export class NetworkComponent implements AfterViewInit, OnDestroy {
  @ViewChild('chart') chartElement!: ElementRef<HTMLDivElement>;
  stage = input(-1);
  selected = output<string>();
  private chart?: echarts.ECharts;
  private observer?: ResizeObserver;
  constructor() { effect(() => { this.stage(); this.draw(); }); }
  ngAfterViewInit() {
    this.chart = echarts.init(this.chartElement.nativeElement); this.draw();
    this.chart.on('click', params => { if (AGENTS.some(agent => agent.id === params.name)) this.selected.emit(params.name ?? 'aura'); });
    this.observer = new ResizeObserver(() => { this.chart?.resize(); this.draw(); }); this.observer.observe(this.chartElement.nativeElement);
  }
  private draw() {
    if (!this.chart) return;
    const stage = this.stage();
    const node = (name: string, label: string, x: number, y: number, color: string, size: number, symbol: string) => ({
      name, x, y, symbolSize: size, value: label,
      itemStyle: { color: '#0e1725', borderColor: color, borderWidth: 1.5, shadowBlur: stage >= 0 ? 24 : 12, shadowColor: color + '55' },
      label: { show: true, formatter: `{icon|${symbol}}\n{name|${label}}`, position: 'inside', rich: { icon: { color, fontSize: size > 70 ? 24 : 17, lineHeight: 28, fontFamily: 'Space Grotesk' }, name: { color: '#ccd8e9', fontSize: 10, lineHeight: 20, fontFamily: 'DM Sans' } } }
    });
    const nodes = [node('user','User Agent',70,160,'#58b5ff',76,'U'),node('nexus','NEXUS',265,160,'#69baff',105,'N'),node('aura','Aura Creative',440,62,'#ae8aff',78,'AC'),node('pixel','Pixel Forge',455,178,'#55b6ff',68,'PF'),node('nova','Nova Studio',365,285,'#48dfb3',68,'NS'),node('vector','Vector Labs',215,307,'#e9b65d',59,'VL'),node('verify','Sentinel',195,25,'#61e1d4',62,'SE'),node('paypal','PayPal',570,285,'#50adff',77,'P')];
    const links = [['user','nexus'],['nexus','aura'],['nexus','pixel'],['nexus','nova'],['nexus','vector'],['nexus','verify'],['aura','paypal'],['verify','aura'],['nova','paypal']].map(([source,target], index) => ({ source, target, lineStyle: { color: index === 1 || index === 6 ? '#8066d8' : '#2c5069', width: index === stage % 7 ? 2.5 : 1, opacity: index === stage % 7 ? 1 : .65, curveness: index === 7 ? .18 : .08, type: index > 6 ? 'dashed' : 'solid' } }));
    const graphWidth = Math.min(this.chart.getWidth() * .82, this.chart.getHeight() * 1.5);
    this.chart.setOption({ animationDurationUpdate: 600, tooltip: { formatter: (params: any) => params.dataType === 'node' ? `${params.data.value}${AGENTS.find(agent => agent.id === params.name) ? '<br/>Trust: ' + AGENTS.find(agent => agent.id === params.name)?.trust + '/100' : ''}` : 'Trust-verified connection', backgroundColor: '#142033', borderColor: '#2a3c53', textStyle: { color: '#e7eef9' } }, series: [{ type: 'graph', layout: 'none', roam: false, data: nodes, links, emphasis: { focus: 'adjacency', scale: 1.08 }, edgeSymbol: ['none','arrow'], edgeSymbolSize: 5, left: 'center', top: 'middle', width: graphWidth, height: graphWidth * 282 / 500 }] });
  }
  ngOnDestroy() { this.observer?.disconnect(); this.chart?.dispose(); }
}