import { Component, computed, effect, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatSliderModule } from '@angular/material/slider';
import { A11yModule } from '@angular/cdk/a11y';
import { LucideAngularModule, Activity, ArrowDownLeft, ArrowRight, ArrowUpRight, Bell, Check, CheckCheck, CheckCircle2, ChevronDown, ChevronRight, CircleHelp, CreditCard, Download, ExternalLink, Globe2, Layers3, LayoutDashboard, LockKeyhole, Menu, MessagesSquare, Network, Play, Radar, ScanLine, Search, Settings2, ShieldCheck, Sparkles, Terminal, TrendingUp, Wallet, X, Zap, ChartNoAxesCombined, RefreshCw } from 'lucide-angular';
import { AgGridAngular } from 'ag-grid-angular';
import { AllCommunityModule, ColDef, ModuleRegistry, themeQuartz } from 'ag-grid-community';
import { NetworkComponent } from './network.component';
import { NexusService, STAGES, Transaction } from './nexus.service';
ModuleRegistry.registerModules([AllCommunityModule]);
export const NEXUS_ICONS = LucideAngularModule.pick({ Activity, ArrowDownLeft, ArrowRight, ArrowUpRight, Bell, Check, CheckCheck, CheckCircle2, ChevronDown, ChevronRight, CircleHelp, CreditCard, Download, ExternalLink, Globe2, Layers3, LayoutDashboard, LockKeyhole, Menu, MessagesSquare, Network, Play, Radar, ScanLine, Search, Settings2, ShieldCheck, Sparkles, Terminal, TrendingUp, Wallet, X, Zap, ChartNoAxesCombined, RefreshCw });
type View = 'overview' | 'how' | 'simulation' | 'graph' | 'transactions' | 'future';

@Component({
  selector: 'nexus-root', standalone: true,
  imports: [CommonModule, FormsModule, MatTooltipModule, MatSliderModule, A11yModule, AgGridAngular, NetworkComponent, LucideAngularModule],
  templateUrl: './app.component.html'
})
export class AppComponent {
  nexus = inject(NexusService);
  view = signal<View>((['overview','how','simulation','graph','transactions','future'].includes(location.hash.slice(1)) ? location.hash.slice(1) : 'overview') as View);
  mobileNav = signal(false);
  modal = signal<'wallet' | 'settings' | 'notifications' | 'agent' | null>(null);
  search = signal(''); filter = signal('All transactions'); toast = signal(''); stages = STAGES;
  nav: {id: View; label: string; icon: string; badge?: string}[] = [
    { id: 'overview', label: 'Overview', icon: 'layout-dashboard' }, { id: 'how', label: 'How Nexus works', icon: 'layers-3' },
    { id: 'simulation', label: 'Live simulation', icon: 'activity', badge: 'LIVE' }, { id: 'graph', label: 'Trust network', icon: 'network' },
    { id: 'transactions', label: 'Transactions', icon: 'credit-card' }, { id: 'future', label: 'The bigger picture', icon: 'globe-2' }
  ];
  pageTitle = computed(() => this.nav.find(item => item.id === this.view())?.label ?? 'Overview');
  rows = computed(() => this.nexus.transactions().filter(row => `${row.agent} ${row.id} ${row.task}`.toLowerCase().includes(this.search().toLowerCase()) && (this.filter() === 'All transactions' || row.status === this.filter())));
  gridTheme = themeQuartz.withParams({ backgroundColor: '#0d131e', foregroundColor: '#dce5f2', headerBackgroundColor: '#111a28', headerTextColor: '#8393a9', borderColor: '#202b3c', rowBorder: { color: '#1b2636' }, fontFamily: 'DM Sans', fontSize: 13, spacing: 7, accentColor: '#65b7ff' });
  columns: ColDef<Transaction>[] = [
    { field: 'agent', headerName: 'Service agent', minWidth: 160, flex: 1.3 },
    { field: 'trust', headerName: 'Trust score', minWidth: 125, flex: 1, valueFormatter: params => `${params.value} / 100`, cellStyle: { color: '#59d9b1' } },
    { field: 'value', headerName: 'Contract value', minWidth: 140, flex: 1, valueFormatter: params => `$${Number(params.value).toFixed(2)} USD` },
    { field: 'status', headerName: 'Contract status', minWidth: 150, flex: 1, cellStyle: { color: '#59d9b1' } },
    { field: 'payment_status', headerName: 'Settlement', minWidth: 160, flex: 1 },
    { field: 'delivery', headerName: 'Delivery score', minWidth: 140, flex: 1, valueFormatter: params => `${params.value}%` },
    { field: 'mode', headerName: 'Environment', minWidth: 125, flex: 1, valueFormatter: params => params.value === 'sandbox' ? 'PayPal sandbox' : 'Simulated' }
  ];
  constructor() {
    window.addEventListener('hashchange', () => { const route = location.hash.slice(1) as View; if (this.nav.some(item => item.id === route)) this.view.set(route); });
    effect(() => { if (this.nexus.engine() === 'server') void this.nexus.loadReputation(this.nexus.selected()); });
  }
  navigate(view: View) { this.view.set(view); location.hash = view; this.mobileNav.set(false); window.scrollTo({ top: 0, behavior: 'smooth' }); }
  launch() { this.navigate('simulation'); void this.nexus.start(); }
  notify(message: string) { this.toast.set(message); setTimeout(() => this.toast.set(''), 3500); }
  inspect(id: string) { this.nexus.selected.set(id); this.modal.set('agent'); }
  exportCsv() {
    const rows = this.rows().map(row => [row.agent,row.trust,row.value,row.status,row.payment_status ?? '',row.delivery,row.mode]);
    const csv = [['Agent','Trust score','Value USD','Status','Settlement','Delivery score','Mode'],...rows].map(row => row.map(value => `"${String(value).replaceAll('"','""')}"`).join(',')).join('\r\n');
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
    const link = document.createElement('a'); link.href = url; link.download = 'nexus-transactions.csv'; link.click(); URL.revokeObjectURL(url);
  }
}