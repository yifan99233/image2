export const CREDIT_BALANCE_CHANGED_EVENT = "image2:credits-changed";

export const notifyCreditBalanceChanged = () => {
  window.dispatchEvent(new CustomEvent(CREDIT_BALANCE_CHANGED_EVENT));
};
