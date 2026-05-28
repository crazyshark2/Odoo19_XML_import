# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class ProductEnrichmentWizard(models.TransientModel):
    """Ürün Zenginleştirme Sihirbazı"""
    _name = 'product.enrichment.wizard'
    _description = 'Ürün Zenginleştirme Sihirbazı'

    product_id = fields.Many2one('product.template', string='Ürün', required=True)
    search_query = fields.Char(string='Arama Terimi', required=True)

    source_ids = fields.Many2many(
        'product.enrichment.source',
        string='Kaynaklar',
        default=lambda self: self.env['product.enrichment.source'].search([('active', '=', True)]),
    )

    # Sonuçlar
    state = fields.Selection([
        ('search', 'Arama'),
        ('results', 'Sonuçlar'),
        ('done', 'Tamamlandı'),
    ], default='search')

    result_ids = fields.One2many(
        'product.enrichment.result',
        'wizard_id',
        string='Sonuçlar',
    )

    selected_result_id = fields.Many2one(
        'product.enrichment.result',
        string='Seçili Sonuç',
    )

    # Güncelleme seçenekleri
    update_name = fields.Boolean(string='İsim Güncelle', default=True)
    update_description = fields.Boolean(string='Açıklama Güncelle', default=True)
    update_image = fields.Boolean(string='Görsel Güncelle', default=True)
    update_price = fields.Boolean(string='Fiyat Güncelle', default=False)

    def action_search(self):
        """Web'de ara"""
        self.ensure_one()

        if not self.search_query:
            raise UserError(_('Arama terimi giriniz.'))

        # Mevcut sonuçları temizle
        self.result_ids.unlink()

        results = []
        for source in self.source_ids:
            try:
                source_results = source.search_product(self.search_query)
                for r in source_results[:5]:  # Her kaynaktan max 5 sonuç
                    results.append({
                        'wizard_id': self.id,
                        'source_id': source.id,
                        'name': r.get('name', ''),
                        'description': r.get('description', '')[:500] if r.get('description') else '',
                        'image_url': r.get('image_url', ''),
                        'price': r.get('price', 0),
                        'brand': r.get('brand', ''),
                        'sku': r.get('sku', ''),
                        'source_url': r.get('source_url', ''),
                        'raw_data': str(r),
                    })
            except Exception as e:
                _logger.error(f"Arama hatası ({source.name}): {e}")

        if results:
            self.env['product.enrichment.result'].create(results)
            self.state = 'results'
        else:
            raise UserError(_('Hiçbir sonuç bulunamadı.'))

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'product.enrichment.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_apply(self):
        """Seçili sonucu uygula"""
        self.ensure_one()

        if not self.selected_result_id:
            raise UserError(_('Bir sonuç seçiniz.'))

        result = self.selected_result_id
        product = self.product_id
        update_vals = {}
        updated_fields = []

        # İsim
        if self.update_name and result.name and not product.name:
            update_vals['name'] = result.name
            updated_fields.append('İsim')

        # Açıklama
        if self.update_description and result.description:
            update_vals['description_sale'] = result.description
            updated_fields.append('Açıklama')

        # Görsel
        if self.update_image and result.image_url:
            try:
                import requests
                import base64
                response = requests.get(result.image_url, timeout=10)
                if response.status_code == 200:
                    update_vals['image_1920'] = base64.b64encode(response.content)
                    updated_fields.append('Görsel')
            except Exception as e:
                _logger.warning(f"Görsel indirme hatası: {e}")

            update_vals['xml_image_url'] = result.image_url

        # Fiyat
        if self.update_price and result.price:
            update_vals['list_price'] = result.price
            updated_fields.append('Fiyat')

        # Kaynak bilgisi
        update_vals['last_enrichment_date'] = fields.Datetime.now()
        update_vals['enrichment_source'] = result.source_id.name

        if update_vals:
            product.write(update_vals)

        # Log kaydet
        self.env['product.enrichment.log'].create({
            'product_id': product.id,
            'source_id': result.source_id.id,
            'search_query': self.search_query,
            'status': 'success',
            'fields_updated': ', '.join(updated_fields) if updated_fields else 'Hiçbiri',
            'source_url': result.source_url,
        })

        self.state = 'done'

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Başarılı'),
                'message': _('%s alanı güncellendi.') % len(updated_fields),
                'type': 'success',
                'sticky': False,
            }
        }

    def action_back(self):
        """Aramaya geri dön"""
        self.state = 'search'
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'product.enrichment.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }


class ProductEnrichmentResult(models.TransientModel):
    """Zenginleştirme Arama Sonuçları"""
    _name = 'product.enrichment.result'
    _description = 'Zenginleştirme Sonucu'

    wizard_id = fields.Many2one('product.enrichment.wizard', string='Wizard', ondelete='cascade')
    source_id = fields.Many2one('product.enrichment.source', string='Kaynak')

    name = fields.Char(string='Ürün Adı')
    description = fields.Text(string='Açıklama')
    image_url = fields.Char(string='Görsel URL')
    price = fields.Float(string='Fiyat')
    brand = fields.Char(string='Marka')
    sku = fields.Char(string='Stok Kodu')
    source_url = fields.Char(string='Kaynak URL')
    raw_data = fields.Text(string='Ham Veri')


class ProductEnrichmentImportWizard(models.TransientModel):
    """Özel Web Sitesi Toplu Aktarım Sihirbazı"""
    _name = 'product.enrichment.import.wizard'
    _description = 'Web Sitesi Ürün Aktarım Sihirbazı'

    source_id = fields.Many2one(
        'product.enrichment.source',
        string='Kaynak',
        required=True,
        domain=[('source_type', '=', 'custom')],
    )

    import_url = fields.Char(
        string='Aktarım URL',
        help='Ürün listesi sayfası URL\'i',
    )

    max_products = fields.Integer(
        string='Maksimum Ürün',
        default=50,
    )

    create_new = fields.Boolean(
        string='Yeni Ürün Oluştur',
        default=True,
    )

    update_existing = fields.Boolean(
        string='Mevcut Ürünleri Güncelle',
        default=True,
    )

    match_by = fields.Selection([
        ('barcode', 'Barkod'),
        ('sku', 'Stok Kodu'),
        ('name', 'İsim'),
    ], string='Eşleştirme Kriteri', default='barcode')

    # Sonuçlar
    state = fields.Selection([
        ('config', 'Yapılandırma'),
        ('preview', 'Önizleme'),
        ('done', 'Tamamlandı'),
    ], default='config')

    preview_text = fields.Text(string='Önizleme', readonly=True)
    result_text = fields.Text(string='Sonuç', readonly=True)

    def action_preview(self):
        """Ürünleri önizle"""
        self.ensure_one()

        if not self.import_url:
            raise UserError(_('Aktarım URL\'i giriniz.'))

        source = self.source_id
        results = source._search_custom(self.import_url)

        if not results:
            raise UserError(_('Hiçbir ürün bulunamadı. Selector\'ları kontrol edin.'))

        preview_lines = [f"Bulunan ürün sayısı: {len(results)}\n"]
        for i, r in enumerate(results[:10], 1):
            preview_lines.append(f"{i}. {r.get('name', 'İsimsiz')}")
            if r.get('sku'):
                preview_lines.append(f"   Kod: {r.get('sku')}")
            if r.get('barcode'):
                preview_lines.append(f"   Barkod: {r.get('barcode')}")

        if len(results) > 10:
            preview_lines.append(f"\n... ve {len(results) - 10} ürün daha")

        self.preview_text = '\n'.join(preview_lines)
        self.state = 'preview'

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'product.enrichment.import.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_import(self):
        """Ürünleri içe aktar"""
        self.ensure_one()

        source = self.source_id
        results = source._search_custom(self.import_url)

        created = updated = skipped = 0

        for product_data in results[:self.max_products]:
            try:
                # Odoo standart _retrieve_product ile eşleştir (Nilvera/UBL ile aynı mantık)
                product_vals = {}
                if self.match_by == 'barcode' and product_data.get('barcode'):
                    product_vals['barcode'] = product_data['barcode']
                elif self.match_by == 'sku' and product_data.get('sku'):
                    product_vals['default_code'] = product_data['sku']
                elif self.match_by == 'name' and product_data.get('name'):
                    product_vals['name'] = product_data['name']
                existing = None
                if product_vals:
                    product = self.env['product.product']._retrieve_product(**product_vals)
                    if product:
                        existing = product.product_tmpl_id

                vals = {
                    'name': product_data.get('name', 'İsimsiz'),
                    'default_code': product_data.get('sku', ''),
                    'barcode': product_data.get('barcode', ''),
                    'description_sale': product_data.get('description', ''),
                    'xml_image_url': product_data.get('image_url', ''),
                }

                if product_data.get('price'):
                    vals['list_price'] = product_data['price']

                if existing and self.update_existing:
                    existing.write(vals)
                    updated += 1
                elif not existing and self.create_new:
                    vals['xml_source_id'] = source.id if hasattr(source, 'id') else False
                    self.env['product.template'].create(vals)
                    created += 1
                else:
                    skipped += 1

            except Exception as e:
                _logger.error(f"Ürün aktarım hatası: {e}")
                skipped += 1

        self.result_text = f"Oluşturulan: {created}\nGüncellenen: {updated}\nAtlanan: {skipped}"
        self.state = 'done'

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'product.enrichment.import.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_back(self):
        """Yapılandırmaya geri dön"""
        self.state = 'config'
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'product.enrichment.import.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
