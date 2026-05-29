# -*- coding: utf-8 -*-

from odoo import models, fields


class ProductExtraImage(models.Model):
    _name = 'mobilsoft.product.image'
    _description = 'Extra Product Image (mobilsoft fallback)'
    _order = 'sequence'

    product_tmpl_id = fields.Many2one(
        'product.template', string='Product',
        required=True, ondelete='cascade',
    )
    product_variant_id = fields.Many2one(
        'product.product', string='Product Variant',
        ondelete='cascade',
    )
    image_1920 = fields.Image(string='Image', max_width=1920, max_height=1920)
    name = fields.Char(string='Name')
    sequence = fields.Integer(string='Sequence', default=10)
    video_url = fields.Char(string='Video URL')
