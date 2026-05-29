# -*- coding: utf-8 -*-
{
    'name': 'MobilSoft XML Ürün İçe Aktarma',
    'version': '19.0.2.11.0',
    'category': 'MobilSoft/Integrations',
    'summary': 'XML ile ürün içe/dışa aktarma - Zenginleştirme ve Dropshipping desteği',
    'description': """
XML Ürün Yönetimi - Import & Export Modülü
==========================================

**İçe Aktarım (Import):**
- Farklı tedarikçi XML formatlarından ürün içe aktarma
- Ticimax, IdeaSoft, T-Soft, OpenCart, WooCommerce desteği
- Esnek alan eşleştirme (field mapping)
- Otomatik fiyat markup hesaplama
- Stok senkronizasyonu
- Dropshipping sipariş akışı

**Dışa Aktarım (Export):**
- Bayiler için XML link ile ürün paylaşımı
- Farklı XML formatları (Standart, T-Soft, Ticimax, N11, Hepsiburada)
- Fiyat artış/indirim ayarları
- Ürün filtreleme (kategori, marka, etiket)
- Token tabanlı güvenli erişim
    """,
    'author': 'MobilSoft',
    'website': 'https://www.mobilsoft.net',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'product',
        'account',
        'stock',
        'purchase',
        'sale',
        'stock_dropshipping',
        'website_sale',
    ],
    'data': [
        'security/ir_model_access.xml',
        'data/xml_templates.xml',
        'data/enrichment_sources.xml',
        'data/ir_cron.xml',
        'views/xml_field_mapping_views.xml',
        'views/xml_source_views.xml',
        'views/xml_export_views.xml',
        'views/xml_import_log_views.xml',
        'views/product_views.xml',
        'views/sale_order_views.xml',
        'views/menu_views.xml',
        'views/product_enrichment_views.xml',
        'views/xml_variant_mapping_views.xml',
        'views/xml_preview_wizard_views.xml',
        'views/xml_select_path_wizard_views.xml',
    ],
    'external_dependencies': {
        'python': ['beautifulsoup4', 'requests'],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
