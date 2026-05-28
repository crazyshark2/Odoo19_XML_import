# -*- coding: utf-8 -*-

from odoo import models, fields


class XmlPreviewWizard(models.TransientModel):
    _name = 'xml.preview.wizard'
    _description = 'XML Önizleme Sihirbazı'

    structured_view = fields.Text(
        string='Düzenlenmiş',
        readonly=True,
    )
    raw_view = fields.Text(
        string='Orjinal Ürün',
        readonly=True,
    )
    paths_view = fields.Text(
        string='XML Yolları',
        readonly=True,
    )
