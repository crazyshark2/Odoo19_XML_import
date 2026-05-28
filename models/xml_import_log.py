# -*- coding: utf-8 -*-

from odoo import models, fields, api


class XmlImportLog(models.Model):
    """XML İçe Aktarım Logu"""
    _name = 'xml.import.log'
    _description = 'XML İçe Aktarım Logu'
    _order = 'start_time desc'

    source_id = fields.Many2one(
        'xml.product.source',
        string='XML Kaynağı',
        required=True,
        ondelete='cascade',
    )
    source_name = fields.Char(
        related='source_id.name',
        string='Kaynak Adı',
        store=True,
    )
    
    start_time = fields.Datetime(
        string='Başlangıç',
        default=fields.Datetime.now,
    )
    end_time = fields.Datetime(
        string='Bitiş',
    )
    duration = fields.Float(
        string='Süre (saniye)',
        compute='_compute_duration',
        store=True,
    )
    
    state = fields.Selection([
        ('running', 'Çalışıyor'),
        ('done', 'Tamamlandı'),
        ('error', 'Hata'),
    ], string='Durum', default='running')
    
    total_products = fields.Integer(
        string='Toplam Ürün',
    )
    products_created = fields.Integer(
        string='Oluşturulan',
    )
    products_updated = fields.Integer(
        string='Güncellenen',
    )
    products_skipped = fields.Integer(
        string='Atlanan',
    )
    products_failed = fields.Integer(
        string='Hatalı',
    )
    
    error_details = fields.Text(
        string='Hata Detayları',
    )

    @api.depends('start_time', 'end_time')
    def _compute_duration(self):
        for record in self:
            if record.start_time and record.end_time:
                delta = record.end_time - record.start_time
                record.duration = delta.total_seconds()
            else:
                record.duration = 0
