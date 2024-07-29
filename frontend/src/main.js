// This software is released under the terms of the GNU GENERAL PUBLIC LICENSE.
// See LICENSE.txt for full details.
// Copyright 2023 Telemarq Ltd

import { createApp, provide } from 'vue';
import './style.css';
import { DefaultApolloClient } from '@vue/apollo-composable';
import App from './App.vue';
import { createPinia } from 'pinia';
import { apolloClient } from './store';

const pinia = createPinia();
const app = createApp(App);

app.provide(DefaultApolloClient, apolloClient);

app.use(pinia);

app.mount('#app');
