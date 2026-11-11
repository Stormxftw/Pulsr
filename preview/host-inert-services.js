// Inert data hooks only: the real host tooltip imports these for optional hints.
// No UI appearance is mocked, and no application stores/services are booted.
export const useI18n = () => ({t:key => key});
export const useKeybindHint = () => '';
