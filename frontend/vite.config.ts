import {defineConfig} from 'vitest/config';
import react from '@vitejs/plugin-react';
export default defineConfig({
  plugins:[react()],
  server:{proxy:{'/api':{target:'http://127.0.0.1:8000',changeOrigin:true},'/health':{target:'http://127.0.0.1:8000'}}},
  test:{environment:'happy-dom',setupFiles:['fake-indexeddb/auto'],include:['src/**/*.test.ts']},
});
