// pages/view-barcode.js
// [ADDED v10.0.4] Barcode View

import { ICONS } from '../organizer-icon.js?v=10.0.4';

export const BarcodeMixin = (Base) => class extends Base {
  renderBarcodeView(content) {
    content.innerHTML = `
      <div style="text-align:center;padding:40px;display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;">
        <div style="font-size:80px;margin-bottom:20px;color:var(--primary);">${ICONS.barcode}</div>
        <h2 style="color:var(--primary);margin-bottom:15px;">${this._t('barcode_scanner', 'Barcode Scanner')}</h2>
        <p style="color:var(--text-sub);line-height:1.5;margin-bottom:40px;max-width:300px;margin-left:auto;margin-right:auto;">
          Scan grocery products and items to instantly identify and add them to your inventory or shopping list.
        </p>
        <button class="action-btn" style="width:220px;height:55px;background:var(--primary);color:white;font-size:16px;border-radius:28px;display:flex;align-items:center;justify-content:center;gap:10px;box-shadow:0 4px 15px rgba(3,169,244,0.4);" onclick="this.getRootNode().host.handleBarcodeScan()">
          ${ICONS.camera} Start Scanning
        </button>
      </div>`;
  }
};