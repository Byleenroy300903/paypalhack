import { bootstrapApplication } from '@angular/platform-browser';
import { provideAnimationsAsync } from '@angular/platform-browser/animations/async';
import { importProvidersFrom, provideZonelessChangeDetection } from '@angular/core';
import { AppComponent, NEXUS_ICONS } from './app/app.component';

bootstrapApplication(AppComponent, { providers: [provideZonelessChangeDetection(), provideAnimationsAsync(), importProvidersFrom(NEXUS_ICONS)] }).catch(console.error);