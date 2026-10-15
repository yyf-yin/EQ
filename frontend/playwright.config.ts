import { defineConfig } from '@playwright/test'
export default defineConfig({testDir:'./e2e',timeout:60000,workers:1,use:{baseURL:process.env.CDR_E2E_BASE_URL || 'http://127.0.0.1:5173',browserName:'chromium',channel:'chrome',headless:true,viewport:{width:1440,height:1000},trace:'retain-on-failure'},reporter:'list'})
