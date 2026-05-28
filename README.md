# MobilSoft XML Ürün İçe/Dışa Aktarma & Zenginleştirme

![Odoo Version](https://img.shields.io/badge/Odoo-19.0-blue)
![License](https:// img.shields.io/badge/License-LGPL--3-green)

XML/HTML/API tabanlı kaynaklardan ürünleri Odoo'ya aktaran, Odoo ürünlerini XML olarak dışa aktaran ve ürün verilerini web'den zenginleştiren entegrasyon modülü.

**Üç alt sistem:**
- **İçe Aktarım (Import):** XML feed'lerden ürün çekme
- **Dışa Aktarım (Export):** Bayiler için XML ürün paylaşımı
- **Zenginleştirme (Enrichment):** Web scraping ile ürün bilgisi tamamlama

---

## İçindekiler

- [Hangi XML Yapıları Çalışır](#hangi-xml-yapıları-çalışır)
- [Kurulum](#kurulum)
- [İçe Aktarım: Adım Adım](#i̇çe-aktarım-adım-adım)
- [XML Yolu Yazma Rehberi](#xml-yolu-yazma-rehberi)
- [Gerçek XML Örnekleri ve Eşleştirmeler](#gerçek-xml-örnekleri-ve-eşleştirmeler)
- [Varyantlı Ürünler](#varyantlı-ürünler)
- [Dönüşüm Tipleri (Transform)](#dönüşüm-tipleri-transform)
- [Dışa Aktarım (Export)](#dışa-aktarım-export)
- [Ürün Zenginleştirme (Enrichment)](#ürün-zenginleştirme-enrichment)
- [Dropshipping Akışı](#dropshipping-akışı)
- [Otomatik Senkronizasyon (Cron)](#otomatik-senkronizasyon-cron)
- [Sık Sorulan Sorular](#sık-sorulan-sorular)

---

## Hangi XML Yapıları Çalışır

| XML Tipi | Açıklama | Otomatik Tanıma |
|----------|----------|-----------------|
| Düz liste `<Product>` | Her ürün aynı seviyede | XPath ile bulunur |
| İç içe `<Category><Product>` | Kategori altında ürünler | Index Grup/Netex parser'ı |
| Attribute'ler `<Product id="123">` | Element içinde öznitelikler | `@id` yazınca çalışır |
| WordPress/WooCommerce WXR | RSS/XML export | Otomatik tanınır (`wordpress.org/export/`) |
| Google Merchant RSS | `<item>` elementli feed | Alternatif XPath ile bulunur |
| Ticimax, T-Soft, IdeaSoft | E-ticaret platformları | XML şablon seçimi ile |
| SOAP/WSDL servisler | API tabanlı XML | Tesan SOAP desteği var |
| HTML sayfalar (enrichment) | Web scraping | BeautifulSoup ile ayrı sistem |

**Kök Element (XPath) hâlâ zorunludur.** `//Products/Product` gibi bir XPath ile ürün elementinin hangisi olduğunu belirtmeniz gerekir. Eğer XPath yanlışsa hiçbir ürün bulunamaz.

---

## Kurulum

1. Modülü `custom-addons` klasörüne kopyalayın
2. Odoo'yu yeniden başlatın
3. Uygulamalar menüsünden "MobilSoft XML Ürün İçe Aktarma" modülünü kurun

**Bağımlılıklar:** `base`, `product`, `account`, `stock`, `purchase`, `sale`, `stock_dropshipping`, `website_sale`

**Python paketleri:** `beautifulsoup4`, `requests` (otomatik kurulmazsa `pip install beautifulsoup4 requests`)

---

## İçe Aktarım: Adım Adım

### 1. XML Kaynağı Oluşturma

Menü: **Stok > Yapılandırma > XML Kaynakları > Oluştur**

| Alan | Açıklama | Zorunlu |
|------|----------|---------|
| **Kaynak Adı** | Feed'in tanımlayıcı adı | Evet |
| **XML URL** | XML dosyasının web adresi (veya yerel dosya yolu) | Evet |
| **XML Şablonu** | Ticimax, T-Soft, WooCommerce vb. hazır şablon — "Özel" de seçebilirsiniz | Evet |
| **Kök Element (XPath)** | Ürünlerin bulunduğu XPath. Varsayılan: `//Product` | Evet |
| **Tedarikçi** | Dropshipping için bağlantılı tedarikçi | Hayır |
| **Kullanıcı Adı / Şifre** | HTTP Basic Auth korumalı feed'ler için | Hayır |

**İpucu:** Kaynağı kaydettikten sonra "XML Yollarını Keşfet" butonuna tıklayın. Modül XML'i çeker, ürün elementlerini bulur ve içindeki tüm alt yolları otomatik tespit eder.

### 2. Alan Eşleştirmeleri

Her XML kaynağına ait alan eşleştirmeleri, kaynağın "Alan Eşleştirmeleri" sekmesinde tanımlanır.

**Her eşleştirme satırı için:**

| Alan | Açıklama |
|------|----------|
| **Odoo Alanı** | Hangi Odoo alanına yazılacak (ürün kodu, ad, fiyat, stok vb.) |
| **XML Yolu** | XML'deki elementin yolu (aşağıdaki rehbere bakın) |
| **XML Yolu Seç** | Keşfedilen yollardan seçmek için Many2one — veya direkt yazabilirsiniz |
| **Dönüşüm** | Değere uygulanacak dönüşüm (büyük harf, regex vb.) |
| **Varsayılan Değer** | XML'de alan boşsa kullanılacak değer |
| **Zorunlu** | İşaretliyse bu alan boş olduğunda ürün atlanır |

**Önemli:** Liste görünümünde satıra tıklayınca form açılır. Formda `XML Yolu Seç` alanı Many2one olarak çalışır — **yazarken öneri gösterir + olmayan yolu yazıp yeni kayıt oluşturabilirsiniz**.

### 3. Ürünleri Çekme

- **Manuel:** Kaynak formunda "Ürünleri Şimdi Çek" butonu
- **Otomatik:** Kaynakta "Otomatik İçe Aktar" işaretliyse cron her saat çalıştırır

### 4. Logları İzleme

Her içe aktarım sonrası kaydın altına log eklenir:
- Toplam ürün sayısı
- Oluşturulan / Güncellenen / Atlanan ürünler
- Hatalı ürünler ve hata nedeni

---

## XML Yolu Yazma Rehberi

| Desen | Açıklama | Örnek XML | XML Yolu |
|-------|----------|-----------|----------|
| **Düz element** | En basit, doğrudan element adı | `<ProductCode>123</ProductCode>` | `ProductCode` |
| **İç içe element** | Üst elementi `/` ile ayırın | `<Category><Name>Elektronik</Name></Category>` | `Category/Name` |
| **Attribute** | Elementin özniteliği | `<Product id="12345">` | `@id` |
| **Dizi indeksi** | Aynı ada sahip çoklu elementler | `<Images><Image>url1</Image><Image>url2</Image></Images>` | `Images/Image[0]` veya `Images/Image[1]` |
| **Attribute + element** | Karışık yapılar | `<Category><Name TR="true">Elektronik</Name></Category>` | `Category/Name/@TR` |
| **Namespace temizlenir** | `xmlns` etiketleri otomatik kaldırılır | `<ns:Product>` | `Product` (ns'siz yazın) |

### Sık Kullanılan XML Yolları

| XML | Yol |
|-----|-----|
| `<ProductCode>STK001</ProductCode>` | `ProductCode` |
| `<Name><![CDATA[Ürün Adı]]></Name>` | `Name` |
| `<Price currency="TRY">99.90</Price>` | `Price` (değer), `@currency` (attribute) |
| `<Category><Name>Elektronik</Name><Code>ELK</Code></Category>` | `Category/Name`, `Category/Code` |
| `<Images><Image>https://...</Image><Image>https://...</Image></Images>` | `Images/Image[0]` (ilk), `Images/Image[1]` (ikinci) |
| `@id` | `<Product id="12345">` |
| `<Variant><Color>Kırmızı</Color><Size>XL</Size></Variant>` | Varyant yapısı — özel işlenir |

---

## Gerçek XML Örnekleri ve Eşleştirmeler

### Örnek 1: Basit XML (Tek Düzey)

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Products>
  <Product>
    <ProductCode>URUN001</ProductCode>
    <ProductName>Örnek Ürün</ProductName>
    <Price>199.99</Price>
    <Currency>TRY</Currency>
    <Stock>50</Stock>
    <CategoryName>Elektronik</CategoryName>
    <Description>Ürün açıklaması burada</Description>
    <ImageURL>https://example.com/image.jpg</ImageURL>
  </Product>
</Products>
```

**Kök Element XPath:** `//Product`

**Alan Eşleştirmeleri:**

| Odoo Alanı | XML Yolu | Dönüşüm |
|------------|----------|---------|
| `default_code` | `ProductCode` | Yok |
| `name` | `ProductName` | Başlık |
| `list_price` | `Price` | Sayıya Çevir |
| `type` | — | Varsayılan: `consu` |
| `categ_id` | `CategoryName` | Yok (kategori adından otomatik oluşturulur) |
| `description` | `Description` | HTML Temizle |
| `image_1920` | `ImageURL` | Yok (URL'den çeker) |
| `qty_available` | `Stock` | Yok |

### Örnek 2: İç İçe Kategorili XML

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Urunler>
  <Urun>
    <UrunKodu>ABC-001</UrunKodu>
    <UrunAdi>Laptop X200</UrunAdi>
    <Fiyat>
      <KDVDahil>12599.00</KDVDahil>
      <KDVHaric>10587.39</KDVHaric>
    </Fiyat>
    <Kategori>
      <AnaKategori>Elektronik</AnaKategori>
      <AltKategori>Dizüstü Bilgisayar</AltKategori>
    </Kategori>
    <Resimler>
      <Resim>https://cdn.example.com/1.jpg</Resim>
      <Resim>https://cdn.example.com/2.jpg</Resim>
    </Resimler>
    <StokBilgisi>
      <Miktar unit="adet">25</Miktar>
      <Depo>Ana Depo</Depo>
    </StokBilgisi>
  </Urun>
</Urunler>
```

**Kök Element XPath:** `//Urun` (alternatifler: `//Product`, `//item`, `.//urun` — deneme yanılma ile bulunur)

**Alan Eşleştirmeleri:**

| Odoo Alanı | XML Yolu | Açıklama |
|------------|----------|----------|
| `default_code` | `UrunKodu` | Basit düz element |
| `name` | `UrunAdi` | |
| `list_price` | `Fiyat/KDVDahil` | İç içe yol |
| `categ_id` | `Kategori/AltKategori` | Kategori iç içe |
| `image_1920` | `Resimler/Resim[0]` | Dizinin ilk elemanı |
| `image_2` | `Resimler/Resim[1]` | Dizinin ikinci elemanı |
| `qty_available` | `StokBilgisi/Miktar` | İç içe yol |
| `uom_id` | — | Varsayılan: `Birimler` |

### Örnek 3: Attribute Kullanan XML

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Products>
  <Product id="5001" status="active">
    <Name>Oyun Koltuğu</Name>
    <Price currency="TRY">8500.00</Price>
    <Category id="12" parent_id="5">Oyuncak</Category>
    <Attributes>
      <Attribute name="Renk" value="Siyah"/>
      <Attribute name="Ağırlık" value="25kg"/>
    </Attributes>
  </Product>
</Products>
```

**Alan Eşleştirmeleri:**

| Odoo Alanı | XML Yolu | Açıklama |
|------------|----------|----------|
| `default_code` | `@id` | Attribute'den ürün kodu |
| `name` | `Name` | |
| `list_price` | `Price` | Element değeri |
| `categ_id` | `Category` | Element değeri (kategori adı) |
| `description` | `Category/@id` | Attribute değeri (Opsiyonel) |

### Örnek 4: WooCommerce / WordPress WXR XML

```xml
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
     xmlns:excerpt="http://wordpress.org/export/1.2/excerpt/"
     xmlns:content="http://purl.org/rss/1.0/modules/content/"
     xmlns:w3c="http://www.w3.org/1999/xhtml"
     xmlns:dc="http://purl.org/dc/elements/1.1/"
     xmlns:wp="http://wordpress.org/export/1.2/">
  <channel>
    <item>
      <title>Örnek Ürün</title>
      <wp:post_type>product</wp:post_type>
      <content:encoded><![CDATA[Ürün açıklaması]]></content:encoded>
      <wp:postmeta>
        <wp:meta_key>_price</wp:meta_key>
        <wp:meta_value>199.99</wp:meta_value>
      </wp:postmeta>
      <wp:postmeta>
        <wp:meta_key>_sku</wp:meta_key>
        <wp:meta_value>URUN001</wp:meta_value>
      </wp:postmeta>
    </item>
  </channel>
</rss>
```

Bu XML'ler **otomatik tanınır** — `wordpress.org/export/` içeren XML'ler `_parse_wordpress_wxr_xml` ile özel işlenir. Ayrıca attachment ve sayfa türleri otomatik filtrelenir, sadece `product` tipindeki kayıtlar alınır.

### Örnek 5: Google Merchant RSS Feed

```xml
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:g="http://base.google.com/ns/1.0">
  <channel>
    <item>
      <g:id>TR123456</g:id>
      <title>Akıllı Saat Pro</title>
      <description>Saat açıklaması</description>
      <g:price>2499.00 TRY</g:price>
      <g:condition>new</g:condition>
      <g:image_link>https://example.com/saat.jpg</g:image_link>
      <g:availability>in_stock</g:availability>
      <g:brand>TeknoMarka</g:brand>
      <g:google_product_category>Elektronik > Giyilebilir</g:google_product_category>
    </item>
  </channel>
</rss>
```

**Kök Element XPath:** `//item`

**Alan Eşleştirmeleri:**

| Odoo Alanı | XML Yolu | Not |
|------------|----------|-----|
| `default_code` | `id` | `g:` namespace'i otomatik temizlenir |
| `name` | `title` | |
| `description` | `description` | |
| `list_price` | `price` | Fiyat Formatı dönüşümüyle `2499.00 TRY → 2499.00` |
| `image_1920` | `image_link` | |
| `brand` | `brand` | (extra alan) |

### Örnek 6: Ticimax XML

```xml
<?xml version="1.0" encoding="UTF-8"?>
<xml>
  <product>
    <productCode>URUN-001</productCode>
    <productName>Test Ürün</productName>
    <stock>150</stock>
    <price1>299.99</price1>
    <price2>349.99</price2>
    <category1>Elektronik</category1>
    <category2>Bilgisayar</category2>
    <images>
      <image>https://cdn.ticimax.com/1.jpg</image>
      <image>https://cdn.ticimax.com/2.jpg</image>
    </images>
    <description>Ürün detayı</description>
    <brandName>Marka</brandName>
    <currency>TL</currency>
    <vat>20</vat>
    <variantInfo>
      <variant>
        <variantName>Renk</variantName>
        <variantValue>Kırmızı</variantValue>
      </variant>
    </variantInfo>
  </product>
</xml>
```

**XML Şablonu:** Ticimax seçilirse otomatik `action_load_template_mappings` ile varsayılan eşleştirmeler yüklenir.

---

## Varyantlı Ürünler

Varyant desteği iki şekilde çalışır:

### Düz Varyantlar (`Variants/Variant/Color`)

```xml
<Product>
  <ProductCode>URUN-ANA</ProductCode>
  <ProductName>Tişört</ProductName>
  <Variants>
    <Variant>
      <Color>Kırmızı</Color>
      <Size>M</Size>
      <Price>149.99</Price>
      <Stock>25</Stock>
    </Variant>
    <Variant>
      <Color>Mavi</Color>
      <Size>L</Size>
      <Price>149.99</Price>
      <Stock>30</Stock>
    </Variant>
  </Variants>
</Product>
```

**Kurulum:**
1. Odoo Alanı = `Varyant Özellik Değeri` seçin
2. XML Yolu = `Variants/Variant/Color`
3. **Varyant Özelliği** alanından "Renk" seçin
4. Aynı şekilde `Size` için ikinci bir mapping ekleyin
5. "Değerleri Tespit Et" butonu ile varyant kombinasyonlarını otomatik oluşturun

### İç İçe Varyantlar (`VariantAttributes/Attribute`)

```xml
<Product>
  <ProductCode>GOM-001</ProductCode>
  <ProductName>Gömlek</ProductName>
  <Variants>
    <Variant>
      <VariantAttributes>
        <Attribute>
          <Name>Renk</Name>
          <Value>Beyaz</Value>
        </Attribute>
        <Attribute>
          <Name>Beden</Name>
          <Value>39</Value>
        </Attribute>
      </VariantAttributes>
    </Variant>
  </Variants>
</Product>
```

**Kurulum:**
1. Odoo Alanı = `Varyant Özellik Değeri`
2. XML Yolu = `Variants/Variant/VariantAttributes/Attribute`
3. **Varyant Özelliği** boş bırakılır
4. **Özellik Adı Alt Yolu** = `Name`
5. **Özellik Değeri Alt Yolu** = `Value`

---

## Dönüşüm Tipleri (Transform)

| Dönüşüm | Etkisi | Örnek Girdi → Çıktı |
|---------|--------|---------------------|
| Yok | Olduğu gibi alır | `Ürün Adı` → `Ürün Adı` |
| BÜYÜK HARF | Tüm harfleri büyütür | `ürün` → `ÜRÜN` |
| küçük harf | Tüm harfleri küçültür | `ÜRÜN` → `ürün` |
| Başlık Formatı | İlk harfleri büyütür | `ürün adı` → `Ürün Adı` |
| Boşlukları Temizle | Gereksiz boşlukları siler | `  çok   boşluk  ` → `çok boşluk` |
| Sayıya Çevir | Sadece rakam+`.`+`,` kalır | `Fiyat: 1.234,56 TL` → `1234.56` |
| Fiyat Formatı | TL formatını düzeltir | `1.234,56` → `1234.56` |
| HTML Etiketlerini Kaldır | `<b>`, `<br>` temizlenir | `<b>Açıklama</b><br/>` → `Açıklama` |
| Regex ile Temizle | Kendi regex'inizi yazın | `(.*)` deseniyle `(123) 456` → `123456` |

### Regex Dönüşüm Örnekleri

| Amaç | Pattern | Replace | Girdi → Çıktı |
|------|---------|---------|---------------|
| Sadece rakam | `[^\d]` | `` | `ABC-123-XYZ` → `123` |
| Parantezleri temizle | `[()]` | `` | `(500)` → `500` |
| Format değiştir | `(\d{3})(\d{3})(\d{4})` | `+90 ($1) $2 $3` | `5321234567` → `+90 (532) 123 4567` |
| Marka ayıkla | `^(.+?)\s-` | `$1` | `Apple - iPhone 15` → `Apple` |

---

## Dışa Aktarım (Export)

Bayileriniz veya pazar yerleri için Odoo ürünlerinizi XML olarak paylaşabilirsiniz.

**Kurulum:**
1. Menü: **XML Ürün > Dışa Aktarım > XML Export Kaynakları > Oluştur**
2. **Kaynak Adı:** "Bayi XML" gibi
3. **Filtre:** Tüm ürünler / Kategoriye göre / Tedarikçiye göre
4. **XML Formatı:** Standart, T-Soft, Ticimax, N11, Hepsiburada
5. Kaydedince **erişim token'ı** otomatik oluşur

**Bayiye verilecek link:**
```
https://sirketiniz.com/xml/export/TOKEN?pass=SIFRE
```

**Özellikler:**
- Token + password ile güvenli erişim
- Çoklu format desteği
- Fiyat markup (kar marjı ekleme)
- Stok ve kategori filtreleme
- Her erişim loglanır

---

## Ürün Zenginleştirme (Enrichment)

Ürün bilgilerini web'den otomatik tamamlar.

**Desteklenen kaynaklar:**
- **Türkiye:** Hepsiburada, Trendyol, N11
- **Global:** Amazon, Google Shopping, UPC Database
- **Özel:** Kendi web siteniz (CSS selector tanımlayarak)

**Kullanım:**
- **Tek ürün:** Ürün formunda "Zenginleştir" butonu
- **Toplu:** Ürün listesinde birden çok ürün seçip aksiyon
- **Otomatik:** Yeni ürün oluştuğunda otomatik çalışsın (opsiyonel)

---

## Dropshipping Akışı

Bu modül ile dropshipping sürecini tamamen yönetebilirsiniz:

1. **XML Kaynağı** oluşturun ve tedarikçiyi bağlayın
2. **Ürünleri çekin** — ürünler otomatik oluşturulur, `xml_source_id` ile işaretlenir
3. **Müşteri siparişi** gelince — siparişte dropship ürün varsa otomatik algılanır
4. **"Dropship Siparişleri Oluştur"** butonu ile tedarikçiye satınalma siparişi gönderilir
5. Tedarikçi siparişi kargoya verince — **stok düşmez**, ürün tedarikçiden direkt müşteriye gider

**Ürünlerde dropshipping alanları:**
| Alan | Açıklama |
|------|----------|
| `xml_source_id` | Hangi XML kaynağından geldiği |
| `is_dropship` | Dropship ürünü mü? |
| `xml_supplier_id` | Tedarikçi (res.partner) |
| `xml_supplier_sku` | Tedarikçinin stok kodu |
| `xml_supplier_price` | Tedarikçi fiyatı |

---

## Otomatik Senkronizasyon (Cron)

Cron **her saat** çalışır, `auto_sync=True` olan tüm kaynakları kontrol eder:
- `next_sync <= şimdi` ise ürünleri çeker
- Aynı cron tüm kaynakları sırayla işletir
- Manuel çekme ile cron aynı anda çalışabilir

**Cron zamanlaması** kaynak bazında değil, küreseldir — yani 1 saatte bir tüm kaynaklar taranır.

---

## Sık Sorulan Sorular

### XML'deki element yolunu nasıl bulurum?

"XML Yollarını Keşfet" butonuna tıklayın. İlk 3 ürün taranır ve tüm alt element yolları + örnek değerleri listelenir. Veya XML'i tarayıcıda açıp element yapısını inceleyin.

### Dropdown'da olmayan bir yol yazmak istiyorum?

`XML Yolu` alanı **fields.Char**'dır — direkt yazabilirsiniz. Ayrıca `XML Yolu Seç` alanı Many2one'dur: yazarken öneri gösterir, olmayan bir değer yazarsanız "Oluştur: ..." seçeneği ile yeni kayıt yaratabilirsiniz.

### Birden çok XML kaynağım var, ürünler karışır mı?

Her ürün `xml_source_id` ile hangi kaynaktan geldiği işaretlenir. Ancak `_find_existing_product` metodu **kaynak filtresi uygulamadan** tüm ürünlerde arama yapar — aynı SKU'ya sahip ürün varsa başka kaynağa ait olsa bile onu günceller.

### Varyantlı ürünler nasıl çalışır?

XML'de `<Variants><Variant>` yapısı varsa otomatik düzleştirilir: her varyant ayrı bir ürün olarak işlenir, `xml_variant_group` ile ana ürüne bağlanır. Detaylar için yukarıdaki "Varyantlı Ürünler" bölümüne bakın.

### Hata alıyorum, XML okunamıyor?

1. URL'nin erişilebilir olduğunu kontrol edin (tarayıcıda açın)
2. `_fetch_xml` 3 kez dener, encoding otomatik algılanır
3. Bazı siteler (tahtakale gibi) session/referer ister — özel işlenir
4. XML namespace'leri (`xmlns`) otomatik temizlenir
5. WordPress WXR ve Index Grup/Netex özel parser'lar ile işlenir

---

## Teknik Detaylar

### Model Yapısı

| Model | Dosya | Açıklama |
|-------|-------|----------|
| `xml.product.source` | `xml_source.py` | XML kaynağı (4831 satır) |
| `xml.field.mapping` | `xml_field_mapping.py` | Alan eşleştirmeleri |
| `xml.source.path` | `xml_source_path.py` | Keşfedilen XML yolları |
| `xml.import.log` | `xml_import_log.py` | İçe aktarım logları |
| `xml.product.export` | `xml_export.py` | Dışa aktarım kaynağı |
| `product.enrichment.source` | `product_enrichment.py` | Zenginleştirme kaynağı |
| `xml.variant.mapping` | `xml_variant_mapping.py` | Varyant eşleştirme |
| `xml.preview.wizard` | `xml_preview_wizard.py` | XML önizleme sihirbazı |

### API Referansı

| Endpoint | Açıklama |
|----------|----------|
| `GET /xml/export/<token>?pass=<password>` | XML ürün export |
| `GET /xml/export/<token>/info?pass=<password>` | Export durum bilgisi (JSON) |

### Güvenlik

- **base.group_user**: XML kaynaklarını ve ürünleri görüntüleyebilir
- **stock.group_stock_manager**: Tam CRUD yetkisi (oluşturma, düzenleme, silme)
- Sihirbaz modelleri (transient): Tüm kullanıcılar yazabilir
- Export: Token + opsiyonel şifre koruması

---

## Lisans

LGPL-3

## Destek

- Email: info@mobilsoft.net
- Tel: 0850 885 36 37
- Web: https://www.mobilsoft.net

---

*MobilSoft © 2026*
