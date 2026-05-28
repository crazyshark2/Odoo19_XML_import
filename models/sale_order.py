# -*- coding: utf-8 -*-

from odoo import models, fields, api, _


class SaleOrder(models.Model):
    """Satış Siparişi - Dropshipping Desteği"""
    _inherit = 'sale.order'

    has_dropship_products = fields.Boolean(
        string='Dropship Ürün Var',
        compute='_compute_has_dropship',
        store=True,
    )
    
    dropship_purchase_ids = fields.Many2many(
        'purchase.order',
        'sale_purchase_dropship_rel',
        'sale_id',
        'purchase_id',
        string='Dropship Siparişleri',
    )
    
    dropship_status = fields.Selection([
        ('none', 'Dropship Yok'),
        ('pending', 'Bekliyor'),
        ('ordered', 'Sipariş Verildi'),
        ('shipped', 'Kargoya Verildi'),
        ('delivered', 'Teslim Edildi'),
    ], string='Dropship Durumu', default='none', compute='_compute_dropship_status', store=True)

    @api.depends('order_line.product_id.is_dropship')
    def _compute_has_dropship(self):
        for order in self:
            order.has_dropship_products = any(
                line.product_id.is_dropship 
                for line in order.order_line 
                if line.product_id
            )

    @api.depends('dropship_purchase_ids', 'dropship_purchase_ids.state')
    def _compute_dropship_status(self):
        for order in self:
            if not order.has_dropship_products:
                order.dropship_status = 'none'
            elif not order.dropship_purchase_ids:
                order.dropship_status = 'pending'
            elif all(po.state in ('purchase', 'done') for po in order.dropship_purchase_ids):
                order.dropship_status = 'ordered'
            else:
                order.dropship_status = 'pending'

    def action_create_dropship_orders(self):
        """Dropship ürünleri için tedarikçi siparişleri oluştur"""
        self.ensure_one()
        
        if not self.has_dropship_products:
            return
        
        # Tedarikçilere göre grupla
        supplier_lines = {}
        
        for line in self.order_line:
            if line.product_id and line.product_id.is_dropship:
                supplier = line.product_id.xml_supplier_id
                if supplier:
                    if supplier.id not in supplier_lines:
                        supplier_lines[supplier.id] = {
                            'supplier': supplier,
                            'lines': [],
                        }
                    supplier_lines[supplier.id]['lines'].append(line)
        
        # Her tedarikçi için satın alma siparişi oluştur
        created_orders = []
        
        for supplier_data in supplier_lines.values():
            supplier = supplier_data['supplier']
            lines = supplier_data['lines']
            
            # Satın alma siparişi oluştur
            po_vals = {
                'partner_id': supplier.id,
                'origin': self.name,
                'notes': _('Dropship sipariş - Müşteri: %s') % self.partner_id.name,
            }
            
            po = self.env['purchase.order'].create(po_vals)
            
            # Sipariş satırlarını ekle
            for sale_line in lines:
                product = sale_line.product_id
                
                po_line_vals = {
                    'order_id': po.id,
                    'product_id': product.id,
                    'name': product.display_name,
                    'product_qty': sale_line.product_uom_qty,
                    'product_uom': sale_line.product_uom.id,
                    'price_unit': product.xml_supplier_price or product.standard_price,
                    'date_planned': fields.Datetime.now(),
                }
                
                self.env['purchase.order.line'].create(po_line_vals)
            
            created_orders.append(po.id)
        
        # İlişkileri kaydet
        if created_orders:
            self.dropship_purchase_ids = [(4, po_id) for po_id in created_orders]
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Dropship Siparişleri Oluşturuldu'),
                'message': _('%s tedarikçi siparişi oluşturuldu.') % len(created_orders),
                'type': 'success',
                'sticky': False,
            }
        }

    def action_view_dropship_orders(self):
        """Dropship satın alma siparişlerini görüntüle"""
        self.ensure_one()
        
        return {
            'type': 'ir.actions.act_window',
            'name': _('Dropship Siparişleri'),
            'res_model': 'purchase.order',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.dropship_purchase_ids.ids)],
        }


class SaleOrderLine(models.Model):
    """Satış Sipariş Satırı"""
    _inherit = 'sale.order.line'

    is_dropship = fields.Boolean(
        string='Dropship',
        related='product_id.is_dropship',
        store=True,
    )
    
    supplier_price = fields.Float(
        string='Tedarikçi Fiyatı',
        related='product_id.xml_supplier_price',
    )
    
    profit = fields.Float(
        string='Kar',
        compute='_compute_profit',
    )

    @api.depends('price_subtotal', 'supplier_price', 'product_uom_qty')
    def _compute_profit(self):
        for line in self:
            if line.supplier_price and line.product_uom_qty:
                line.profit = line.price_subtotal - (line.supplier_price * line.product_uom_qty)
            else:
                line.profit = 0
