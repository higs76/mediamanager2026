-- Migration 012 : normalisation des codes langue (ISO 639)
-- L'auto-découverte créait une ligne `languages` par variante brute ffprobe
-- ('fre','fr','fra' pour le même français) au lieu de les regrouper.
-- Cette migration fusionne les doublons existants vers leur code ISO 639-2/T
-- canonique (réaffecte audio_tracks/subtitle_tracks puis supprime le doublon)
-- et corrige les libellés (auparavant juste code.upper()).
--
-- Toute nouvelle analyse utilise désormais watcher/lang_codes.py pour
-- normaliser en amont (voir analyzer.py::_get_or_create_language).

DO $$
DECLARE
    pairs text[][] := ARRAY[
        -- ISO 639-2/B (bibliographique) → ISO 639-2/T (canonique)
        ['alb','sqi'], ['arm','hye'], ['baq','eus'], ['bur','mya'], ['chi','zho'],
        ['cze','ces'], ['dut','nld'], ['fre','fra'], ['geo','kat'], ['ger','deu'],
        ['gre','ell'], ['ice','isl'], ['mac','mkd'], ['mao','mri'], ['may','msa'],
        ['per','fas'], ['rum','ron'], ['slo','slk'], ['tib','bod'], ['wel','cym'],
        -- ISO 639-1 (2 lettres) → ISO 639-2/T (3 lettres)
        ['aa','aar'], ['ab','abk'], ['af','afr'], ['ak','aka'], ['sq','sqi'],
        ['am','amh'], ['ar','ara'], ['an','arg'], ['hy','hye'], ['as','asm'],
        ['av','ava'], ['ae','ave'], ['ay','aym'], ['az','aze'], ['ba','bak'],
        ['bm','bam'], ['eu','eus'], ['be','bel'], ['bn','ben'], ['bh','bih'],
        ['bi','bis'], ['bs','bos'], ['br','bre'], ['bg','bul'], ['my','mya'],
        ['ca','cat'], ['ch','cha'], ['ce','che'], ['zh','zho'], ['cu','chu'],
        ['cv','chv'], ['kw','cor'], ['co','cos'], ['cr','cre'], ['cs','ces'],
        ['da','dan'], ['dv','div'], ['nl','nld'], ['dz','dzo'], ['en','eng'],
        ['eo','epo'], ['et','est'], ['ee','ewe'], ['fo','fao'], ['fj','fij'],
        ['fi','fin'], ['fr','fra'], ['fy','fry'], ['ff','ful'], ['ka','kat'],
        ['de','deu'], ['gd','gla'], ['ga','gle'], ['gl','glg'], ['gv','glv'],
        ['el','ell'], ['gn','grn'], ['gu','guj'], ['ht','hat'], ['ha','hau'],
        ['he','heb'], ['hz','her'], ['hi','hin'], ['ho','hmo'], ['hr','hrv'],
        ['hu','hun'], ['ig','ibo'], ['is','isl'], ['io','ido'], ['ii','iii'],
        ['iu','iku'], ['ie','ile'], ['ia','ina'], ['id','ind'], ['ik','ipk'],
        ['it','ita'], ['jv','jav'], ['ja','jpn'], ['kl','kal'], ['kn','kan'],
        ['kr','kau'], ['ks','kas'], ['kk','kaz'], ['km','khm'], ['ki','kik'],
        ['rw','kin'], ['ky','kir'], ['kv','kom'], ['kg','kon'], ['ko','kor'],
        ['kj','kua'], ['ku','kur'], ['lo','lao'], ['la','lat'], ['lv','lav'],
        ['li','lim'], ['ln','lin'], ['lt','lit'], ['lb','ltz'], ['lu','lub'],
        ['lg','lug'], ['mk','mkd'], ['mh','mah'], ['ml','mal'], ['mi','mri'],
        ['mr','mar'], ['ms','msa'], ['mg','mlg'], ['mt','mlt'], ['mn','mon'],
        ['na','nau'], ['nv','nav'], ['nr','nbl'], ['nd','nde'], ['ng','ndo'],
        ['ne','nep'], ['nn','nno'], ['nb','nob'], ['no','nor'], ['ny','nya'],
        ['oc','oci'], ['oj','oji'], ['or','ori'], ['om','orm'], ['os','oss'],
        ['pa','pan'], ['fa','fas'], ['pi','pli'], ['pl','pol'], ['pt','por'],
        ['ps','pus'], ['qu','que'], ['rm','roh'], ['ro','ron'], ['rn','run'],
        ['ru','rus'], ['sg','sag'], ['sa','san'], ['si','sin'], ['sk','slk'],
        ['sl','slv'], ['se','sme'], ['sm','smo'], ['sn','sna'], ['sd','snd'],
        ['so','som'], ['st','sot'], ['es','spa'], ['sc','srd'], ['sr','srp'],
        ['ss','ssw'], ['su','sun'], ['sw','swa'], ['sv','swe'], ['ty','tah'],
        ['ta','tam'], ['tt','tat'], ['te','tel'], ['tg','tgk'], ['tl','tgl'],
        ['th','tha'], ['bo','bod'], ['ti','tir'], ['to','ton'], ['tn','tsn'],
        ['ts','tso'], ['tk','tuk'], ['tr','tur'], ['tw','twi'], ['ug','uig'],
        ['uk','ukr'], ['ur','urd'], ['uz','uzb'], ['ve','ven'], ['vi','vie'],
        ['vo','vol'], ['wa','wln'], ['wo','wol'], ['xh','xho'], ['yi','yid'],
        ['yo','yor'], ['za','zha'], ['zu','zul'], ['cy','cym']
    ];
    p text[];
    dup_id   integer;
    canon_id integer;
BEGIN
    FOREACH p SLICE 1 IN ARRAY pairs LOOP
        SELECT id INTO dup_id   FROM languages WHERE code = p[1];
        SELECT id INTO canon_id FROM languages WHERE code = p[2];

        IF dup_id IS NOT NULL AND canon_id IS NOT NULL AND dup_id <> canon_id THEN
            UPDATE audio_tracks    SET language_id = canon_id WHERE language_id = dup_id;
            UPDATE subtitle_tracks SET language_id = canon_id WHERE language_id = dup_id;
            DELETE FROM languages WHERE id = dup_id;
        ELSIF dup_id IS NOT NULL AND canon_id IS NULL THEN
            UPDATE languages SET code = p[2] WHERE id = dup_id;
        END IF;
    END LOOP;
END $$;

-- Libellés français pour les codes canoniques désormais consolidés
UPDATE languages l
SET label = v.label
FROM (VALUES
    ('fra','Français'), ('eng','Anglais'), ('deu','Allemand'), ('spa','Espagnol'),
    ('ita','Italien'), ('por','Portugais'), ('nld','Néerlandais'), ('ell','Grec'),
    ('swe','Suédois'), ('nor','Norvégien'), ('nob','Norvégien (Bokmål)'),
    ('nno','Norvégien (Nynorsk)'), ('dan','Danois'), ('fin','Finnois'),
    ('isl','Islandais'), ('pol','Polonais'), ('ces','Tchèque'), ('slk','Slovaque'),
    ('hun','Hongrois'), ('ron','Roumain'), ('bul','Bulgare'), ('hrv','Croate'),
    ('srp','Serbe'), ('slv','Slovène'), ('ukr','Ukrainien'), ('rus','Russe'),
    ('tur','Turc'), ('ara','Arabe'), ('heb','Hébreu'), ('fas','Persan'),
    ('hin','Hindi'), ('ben','Bengali'), ('urd','Ourdou'), ('tha','Thaï'),
    ('vie','Vietnamien'), ('ind','Indonésien'), ('msa','Malais'),
    ('zho','Chinois'), ('jpn','Japonais'), ('kor','Coréen'),
    ('eus','Basque'), ('cat','Catalan'), ('glg','Galicien'), ('cym','Gallois'),
    ('gle','Irlandais'), ('gla','Gaélique écossais'), ('sqi','Albanais'),
    ('hye','Arménien'), ('kat','Géorgien'), ('mkd','Macédonien'),
    ('bos','Bosniaque'), ('est','Estonien'), ('lav','Letton'), ('lit','Lituanien'),
    ('mlt','Maltais'), ('epo','Espéranto'), ('lat','Latin'),
    ('afr','Afrikaans'), ('swa','Swahili'), ('amh','Amharique'),
    ('und','Indéterminé')
) AS v(code, label)
WHERE l.code = v.code;
