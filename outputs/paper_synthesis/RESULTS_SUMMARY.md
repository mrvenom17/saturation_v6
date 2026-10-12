# Synthesis (pipeline v6.1.2, pre-registration 7442f383)

Study set (pre-registration): 10 cities: Chennai_2015, Valencia_2024, EmiliaRomagna_2023a, Forli_2023b, York_2015, Carlisle_2015, PortoAlegre_2024, TaquariValley_2024, Houston_SanJacinto_2017, Jakarta_2020
- set 'tier A, all (confirmatory)': 9 cities: Carlisle_2015, Chennai_2015, EmiliaRomagna_2023a, Forli_2023b, Houston_SanJacinto_2017, PortoAlegre_2024, TaquariValley_2024, Valencia_2024, York_2015
- set 'tier A, evaluable social layer (sensitivity, added in v6.1)': 7 cities: Chennai_2015, EmiliaRomagna_2023a, Forli_2023b, Houston_SanJacinto_2017, PortoAlegre_2024, TaquariValley_2024, Valencia_2024
- set 'tier A, localisable (conditional)': 1 cities: Chennai_2015
- set 'tier A + A-points': 9 cities: Carlisle_2015, Chennai_2015, EmiliaRomagna_2023a, Forli_2023b, Houston_SanJacinto_2017, PortoAlegre_2024, TaquariValley_2024, Valencia_2024, York_2015
- set 'tier A + A-points, localisable': 1 cities: Chennai_2015
- set 'all localisable (any tier)': 2 cities: Chennai_2015, Jakarta_2020

## Read this first
- Carlisle_2015: layer = mixed signal (geotagged_photo 67%, news 33%); NO EVALUABLE SOCIAL LAYER (6 located mentions): its social effects are noise
- Chennai_2015: layer = news-media signal; label caveat: NRSC inundation zone as redistributed by OpenCity: the source states neither the satellite sensor nor the image date (dataset page re-checked 2 Oct 2026), so the label cannot be tied to a day of the event
- EmiliaRomagna_2023a: layer = mixed signal (news 79%, social_media 21%)
- Forli_2023b: layer = news-media signal
- Houston_SanJacinto_2017: layer = mixed signal (news 77%, social_media 23%, geotagged_photo 0%)
- Jakarta_2020: layer = news-media signal
- PortoAlegre_2024: layer = mixed signal (news 74%, social_media 26%)
- TaquariValley_2024: layer = mixed signal (news 76%, social_media 24%)
- Valencia_2024: layer = news-media signal
- York_2015: layer = mixed signal (news 56%, social_media 33%, geotagged_photo 11%); NO EVALUABLE SOCIAL LAYER (9 located mentions): its social effects are noise
- Verdicts are the pre-registered ones. 'reading' adds whether the whole 90% interval lies inside the SESOI: an effect can be non-zero and still negligible.
- A pooled interval inside the SESOI is not evidence from every city: see the weights and leave-one-out estimates in T11 before describing any pooled result.

RQ3 pooled slope [primary] info_nats_fm_adj: +0.0042 (95% CI -0.0001 to +0.0085; one-sided p (H1: slope < 0)=0.9718; k=9; I2=0.00; tau2=0; PI -0.000 to +0.009)
RQ3 pooled slope [primary] dAP_stacked_fm_adj: -0.0046 (95% CI -0.1191 to +0.1099; one-sided p (H1: slope < 0)=0.4641; k=9; I2=0.73; tau2=0.01388; PI -0.307 to +0.298)
RQ3 pooled slope [headroom_normalised] info_frac_fm_adj: +0.0120 (95% CI +0.0014 to +0.0226; one-sided p (H1: slope < 0)=0.9846; k=9; I2=0.15; tau2=0; PI +0.001 to +0.023)
RQ3 pooled slope [headroom_normalised] dAPh_fm_adj: +0.0202 (95% CI -0.1572 to +0.1976; one-sided p (H1: slope < 0)=0.6002; k=9; I2=0.71; tau2=0.03232; PI -0.442 to +0.483)
RQ3 pooled slope [robust_excl_R0] info_nats_fm_adj: -0.0018 (95% CI -0.0144 to +0.0108; one-sided p (H1: slope < 0)=0.3755; k=9; I2=0.00; tau2=3.457e-05; PI -0.021 to +0.017)
RQ3 pooled slope [robust_excl_R0] dAP_stacked_fm_adj: -0.0122 (95% CI -0.0568 to +0.0323; one-sided p (H1: slope < 0)=0.2722; k=9; I2=0.40; tau2=0.0003165; PI -0.074 to +0.050)

RQ3 moderator [confirmatory] gradient slope info_nats_fm_adj ~ log_effective_locations: slope +0.0079 (SE 0.0140; KH p=0.5922; permutation p=0.3330; k=9); Holm p across the 7 confirmatory moderator tests=1.0000; leave-one-out slope -0.0212 to +0.0128 (sign NOT stable; most influential TaquariValley_2024, slope without it -0.0212)
RQ3 moderator [confirmatory] gradient slope dAP_stacked_fm_adj ~ log_effective_locations: slope -0.0977 (SE 0.0689; KH p=0.1988; permutation p=0.2044; k=9); Holm p across the 7 confirmatory moderator tests=1.0000; leave-one-out slope -0.2086 to +0.0242 (sign NOT stable; most influential Chennai_2015, slope without it +0.0242)
RQ3 moderator [confirmatory] top-rung info_frac_fm ~ log_effective_locations: slope -0.0067 (SE 0.0101; KH p=0.5254; permutation p=0.6207; k=9); Holm p across the 7 confirmatory moderator tests=1.0000; leave-one-out slope -0.0187 to -0.0042 (sign stable; most influential Chennai_2015, slope without it -0.0187)
RQ3 moderator [confirmatory] top-rung dAP_stacked_fm ~ log_effective_locations: slope -0.0129 (SE 0.0057; KH p=0.0562; permutation p=0.0941; k=9); Holm p across the 7 confirmatory moderator tests=0.6591; leave-one-out slope -0.0162 to -0.0082 (sign stable; most influential PortoAlegre_2024, slope without it -0.0082)
RQ3 moderator [confirmatory] top-rung dAP_gated_fm ~ log_effective_locations: slope +0.0060 (SE 0.0063; KH p=0.3754; permutation p=0.1839; k=8); Holm p across the 7 confirmatory moderator tests=1.0000; leave-one-out slope -0.0024 to +0.0179 (sign NOT stable; most influential Chennai_2015, slope without it +0.0179)
RQ3 moderator [confirmatory] top-rung dAP_early_fm ~ log_effective_locations: slope -0.0048 (SE 0.0056; KH p=0.4245; permutation p=0.4640; k=9); Holm p across the 7 confirmatory moderator tests=1.0000; leave-one-out slope -0.0085 to -0.0013 (sign stable; most influential Chennai_2015, slope without it -0.0085)
RQ3 moderator [confirmatory] top-rung dAP_adr_legacy_fm ~ log_effective_locations: slope +0.0115 (SE 0.0268; KH p=0.6813; permutation p=0.6624; k=9); Holm p across the 7 confirmatory moderator tests=1.0000; leave-one-out slope -0.0376 to +0.0610 (sign NOT stable; most influential TaquariValley_2024, slope without it +0.0610)
RQ3 moderator [sensitivity: evaluable social layer] gradient slope info_nats_fm_adj ~ log_effective_locations: slope +0.0122 (SE 0.0144; KH p=0.4326; permutation p=0.1413; k=7)
RQ3 moderator [sensitivity: evaluable social layer] gradient slope dAP_stacked_fm_adj ~ log_effective_locations: slope -0.0771 (SE 0.0758; KH p=0.3556; permutation p=0.3796; k=7)
RQ3 moderator [sensitivity: evaluable social layer] top-rung info_frac_fm ~ log_effective_locations: slope -0.0051 (SE 0.0088; KH p=0.5879; permutation p=0.7617; k=7)
RQ3 moderator [sensitivity: evaluable social layer] top-rung dAP_stacked_fm ~ log_effective_locations: slope -0.0081 (SE 0.0059; KH p=0.2261; permutation p=0.6284; k=7)
RQ3 moderator [sensitivity: evaluable social layer] top-rung dAP_gated_fm ~ log_effective_locations: slope +0.0075 (SE 0.0071; KH p=0.3524; permutation p=0.1625; k=6)
RQ3 moderator [sensitivity: evaluable social layer] top-rung dAP_early_fm ~ log_effective_locations: slope -0.0041 (SE 0.0059; KH p=0.5115; permutation p=0.5790; k=7)
RQ3 moderator [sensitivity: evaluable social layer] top-rung dAP_adr_legacy_fm ~ log_effective_locations: slope +0.0041 (SE 0.0267; KH p=0.8851; permutation p=0.8690; k=7)
RQ3 moderator [exploratory] gradient slope info_nats_fm_adj ~ physical_lift_top_rung: slope +0.0001 (SE 0.0007; KH p=0.8324; permutation p=0.7100; k=9)
RQ3 moderator [exploratory] gradient slope info_nats_fm_adj ~ log_mentions: slope +0.0008 (SE 0.0034; KH p=0.8261; permutation p=0.6669; k=9)
RQ3 moderator [exploratory] gradient slope dAP_stacked_fm_adj ~ physical_lift_top_rung: slope +0.0161 (SE 0.0086; KH p=0.1024; permutation p=0.1026; k=9)
RQ3 moderator [exploratory] gradient slope dAP_stacked_fm_adj ~ log_mentions: slope -0.0529 (SE 0.0171; KH p=0.0176; permutation p=0.0127; k=9)

Influence top-rung info_frac_fm: PortoAlegre_2024 46%, Houston_SanJacinto_2017 36% of the pooled weight; leave-one-out estimate from +0.0018 to +0.0059 (all cities +0.0035 [-0.0028, +0.0098])
Influence top-rung dAP_stacked_fm: PortoAlegre_2024 49%, Houston_SanJacinto_2017 37% of the pooled weight; leave-one-out estimate from +0.0014 to +0.0048 (all cities +0.0021 [-0.0023, +0.0065])
Influence top-rung dAP_gated_fm: Houston_SanJacinto_2017 89%, Forli_2023b 5% of the pooled weight; leave-one-out estimate from -0.0015 to +0.0010 (all cities +0.0008 [-0.0019, +0.0035])
Influence top-rung dAP_early_fm: PortoAlegre_2024 84%, Houston_SanJacinto_2017 12% of the pooled weight; leave-one-out estimate from +0.0000 to +0.0025 (all cities +0.0003 [-0.0020, +0.0026])
Influence top-rung dAP_adr_legacy_fm: Chennai_2015 14%, Forli_2023b 13% of the pooled weight; leave-one-out estimate from -0.0804 to -0.0650 (all cities -0.0716 [-0.1112, -0.0320])
Influence gradient slope info_nats_fm_adj: Houston_SanJacinto_2017 57%, Forli_2023b 37% of the pooled weight; leave-one-out estimate from +0.0033 to +0.0044 (all cities +0.0042 [-0.0001, +0.0085])
Influence gradient slope dAP_stacked_fm_adj: Forli_2023b 16%, York_2015 16% of the pooled weight; leave-one-out estimate from -0.0265 to +0.0404 (all cities -0.0046 [-0.1191, +0.1099])

RQ1 pooled top rung [tier A, all (confirmatory)] info_frac_fm: +0.0035 (95% CI -0.0028 to +0.0098; k=9; I2=0.55)
RQ1 pooled top rung [tier A, all (confirmatory)] dAP_stacked_fm: +0.0021 (95% CI -0.0023 to +0.0065; k=9; I2=0.58)
RQ1 pooled top rung [tier A, all (confirmatory)] dAP_gated_fm: +0.0008 (95% CI -0.0019 to +0.0035; k=8; I2=0.00)
RQ1 pooled top rung [tier A, all (confirmatory)] dAP_early_fm: +0.0003 (95% CI -0.0020 to +0.0026; k=9; I2=0.13)
RQ1 pooled top rung [tier A, all (confirmatory)] dAP_adr_legacy_fm: -0.0716 (95% CI -0.1112 to -0.0320; k=9; I2=0.94)
RQ1 pooled top rung [tier A, evaluable social layer (sensitivity, added in v6.1)] info_frac_fm: +0.0033 (95% CI -0.0022 to +0.0088; k=7; I2=0.46)
RQ1 pooled top rung [tier A, evaluable social layer (sensitivity, added in v6.1)] dAP_stacked_fm: +0.0014 (95% CI -0.0017 to +0.0045; k=7; I2=0.43)
RQ1 pooled top rung [tier A, evaluable social layer (sensitivity, added in v6.1)] dAP_gated_fm: +0.0008 (95% CI -0.0024 to +0.0039; k=6; I2=0.15)
RQ1 pooled top rung [tier A, evaluable social layer (sensitivity, added in v6.1)] dAP_early_fm: +0.0003 (95% CI -0.0022 to +0.0027; k=7; I2=0.09)
RQ1 pooled top rung [tier A, evaluable social layer (sensitivity, added in v6.1)] dAP_adr_legacy_fm: -0.0619 (95% CI -0.1048 to -0.0189; k=7; I2=0.95)

RQ2 Carlisle_2015 info_nats_fm_adj: slope -0.0999 [-0.8844, +0.3497], one-sided p=0.4291, Holm p=1.0000
RQ2 Carlisle_2015 dAP_stacked_fm_adj: slope +0.2059 [-0.0724, +0.5406], one-sided p=0.9301, Holm p=1.0000
RQ2 Chennai_2015 info_nats_fm_adj: slope -0.0306 [-0.1087, +0.0774], one-sided p=0.2675, Holm p=1.0000
RQ2 Chennai_2015 dAP_stacked_fm_adj: slope -0.2943 [-0.4810, -0.1540], one-sided p=0.0020, Holm p=0.0359
RQ2 EmiliaRomagna_2023a info_nats_fm_adj: slope +0.0827 [-0.0121, +0.2557], one-sided p=0.9641, Holm p=1.0000
RQ2 EmiliaRomagna_2023a dAP_stacked_fm_adj: slope -0.1587 [-0.3550, +1.1291], one-sided p=0.5329, Holm p=1.0000
RQ2 Forli_2023b info_nats_fm_adj: slope +0.0039 [-0.0006, +0.0112], one-sided p=0.9461, Holm p=1.0000
RQ2 Forli_2023b dAP_stacked_fm_adj: slope +0.0452 [-0.0159, +0.0937], one-sided p=0.9361, Holm p=1.0000
RQ2 Houston_SanJacinto_2017 info_nats_fm_adj: slope +0.0049 [+0.0000, +0.0096], one-sided p=0.9741, Holm p=1.0000
RQ2 Houston_SanJacinto_2017 dAP_stacked_fm_adj: slope -0.0212 [-0.0962, +0.0469], one-sided p=0.2954, Holm p=1.0000
RQ2 Jakarta_2020 info_nats_fm_adj: slope +0.0190 [-0.0361, +0.1089], one-sided p=0.7784 (not in the confirmatory family)
RQ2 Jakarta_2020 dAP_stacked_fm_adj: slope +0.1739 [-0.3729, +0.4496], one-sided p=0.6727 (not in the confirmatory family)
RQ2 PortoAlegre_2024 info_nats_fm_adj: slope -0.0003 [-0.0176, +0.0164], one-sided p=0.5110, Holm p=1.0000
RQ2 PortoAlegre_2024 dAP_stacked_fm_adj: slope +0.1030 [-0.0188, +0.2289], one-sided p=0.9521, Holm p=1.0000
RQ2 TaquariValley_2024 info_nats_fm_adj: slope -0.0365 [-0.0905, -0.0009], one-sided p=0.0259, Holm p=0.4411
RQ2 TaquariValley_2024 dAP_stacked_fm_adj: slope -0.0152 [-0.1017, +0.1369], one-sided p=0.6188, Holm p=1.0000
RQ2 Valencia_2024 info_nats_fm_adj: slope +0.0239 [-0.2033, +0.2977], one-sided p=0.5309, Holm p=1.0000
RQ2 Valencia_2024 dAP_stacked_fm_adj: slope -0.2227 [-0.4605, +0.1031], one-sided p=0.1158, Holm p=1.0000
RQ2 York_2015 info_nats_fm_adj: slope +0.0379 [-0.0214, +0.0858], one-sided p=0.8723, Holm p=1.0000
RQ2 York_2015 dAP_stacked_fm_adj: slope +0.1095 [+0.0641, +0.1876], one-sided p=1.0000, Holm p=1.0000

RQ1 Carlisle_2015 R5_+sar_event info_nats_fm: +0.0104 [-0.3875, +0.2616] -> inconclusive | no evaluable social layer
RQ1 Carlisle_2015 R5_+sar_event info_frac_fm: +0.0193 [-0.5336, +0.5942] -> inconclusive | no evaluable social layer
RQ1 Carlisle_2015 R5_+sar_event dAP_stacked_fm: +0.0110 [-0.0267, +0.0535] -> inconclusive | no evaluable social layer
RQ1 Carlisle_2015 R5_+sar_event dAP_gated_fm: +0.0036 [-0.0211, +0.0587] -> inconclusive | no evaluable social layer
RQ1 Carlisle_2015 R5_+sar_event dAP_early_fm: +0.0256 [+0.0072, +0.0734] -> informative | no evaluable social layer
RQ1 Carlisle_2015 R5_+sar_event dAP_adr_legacy_fm: -0.1582 [-0.2625, -0.0163] -> harmful | no evaluable social layer
RQ1 Chennai_2015 R5_+sar_event info_nats_fm: -0.0007 [-0.0118, +0.0068] -> inconclusive
RQ1 Chennai_2015 R5_+sar_event info_frac_fm: -0.0014 [-0.0222, +0.0135] -> saturated | reading: equivalent to zero (within SESOI)
RQ1 Chennai_2015 R5_+sar_event dAP_stacked_fm: -0.0056 [-0.0282, +0.0158] -> inconclusive
RQ1 Chennai_2015 R5_+sar_event dAP_gated_fm: -0.0031 [-0.0254, +0.0152] -> inconclusive
RQ1 Chennai_2015 R5_+sar_event dAP_early_fm: +0.0039 [-0.0134, +0.0251] -> inconclusive
RQ1 Chennai_2015 R5_+sar_event dAP_adr_legacy_fm: -0.0098 [-0.0194, +0.0036] -> inconclusive
RQ1 EmiliaRomagna_2023a R5_+sar_event info_nats_fm: +0.0122 [-0.0295, +0.0428] -> inconclusive
RQ1 EmiliaRomagna_2023a R5_+sar_event info_frac_fm: +0.0275 [-0.0576, +0.1235] -> inconclusive
RQ1 EmiliaRomagna_2023a R5_+sar_event dAP_stacked_fm: -0.0549 [-0.0781, +0.1013] -> inconclusive
RQ1 EmiliaRomagna_2023a R5_+sar_event dAP_gated_fm: -0.0021 [-0.0073, +0.0181] -> inconclusive
RQ1 EmiliaRomagna_2023a R5_+sar_event dAP_early_fm: -0.0248 [-0.0518, -0.0006] -> harmful
RQ1 EmiliaRomagna_2023a R5_+sar_event dAP_adr_legacy_fm: -0.0553 [-0.0777, +0.0049] -> inconclusive
RQ1 Forli_2023b R5_+sar_event info_nats_fm: +0.0010 [-0.0003, +0.0025] -> inconclusive
RQ1 Forli_2023b R5_+sar_event info_frac_fm: +0.0075 [-0.0023, +0.0177] -> saturated | reading: equivalent to zero (within SESOI)
RQ1 Forli_2023b R5_+sar_event dAP_stacked_fm: +0.0043 [-0.0038, +0.0140] -> inconclusive
RQ1 Forli_2023b R5_+sar_event dAP_gated_fm: +0.0024 [-0.0076, +0.0130] -> inconclusive
RQ1 Forli_2023b R5_+sar_event dAP_early_fm: +0.0085 [-0.0073, +0.0291] -> inconclusive
RQ1 Forli_2023b R5_+sar_event dAP_adr_legacy_fm: -0.0301 [-0.0443, -0.0158] -> harmful
RQ1 Houston_SanJacinto_2017 R5_+sar_event info_nats_fm: +0.0020 [+0.0006, +0.0034] -> inconclusive
RQ1 Houston_SanJacinto_2017 R5_+sar_event info_frac_fm: +0.0058 [+0.0019, +0.0099] -> saturated | reading: equivalent to zero (within SESOI)
RQ1 Houston_SanJacinto_2017 R5_+sar_event dAP_stacked_fm: +0.0030 [+0.0008, +0.0055] -> saturated | reading: equivalent to zero (within SESOI)
RQ1 Houston_SanJacinto_2017 R5_+sar_event dAP_gated_fm: +0.0011 [-0.0012, +0.0035] -> saturated | reading: equivalent to zero (within SESOI)
RQ1 Houston_SanJacinto_2017 R5_+sar_event dAP_early_fm: +0.0022 [-0.0033, +0.0075] -> saturated | reading: equivalent to zero (within SESOI)
RQ1 Houston_SanJacinto_2017 R5_+sar_event dAP_adr_legacy_fm: -0.1124 [-0.1342, -0.0904] -> harmful
RQ1 Jakarta_2020 R5_+sar_event info_nats_fm: -0.0025 [-0.0061, +0.0017] -> inconclusive
RQ1 Jakarta_2020 R5_+sar_event info_frac_fm: -0.0089 [-0.0228, +0.0059] -> inconclusive
RQ1 Jakarta_2020 R5_+sar_event dAP_stacked_fm: -0.0121 [-0.0272, +0.0054] -> inconclusive
RQ1 Jakarta_2020 R5_+sar_event dAP_gated_fm: -0.0097 [-0.0151, +0.0027] -> inconclusive
RQ1 Jakarta_2020 R5_+sar_event dAP_early_fm: -0.0058 [-0.0223, +0.0166] -> inconclusive
RQ1 Jakarta_2020 R5_+sar_event dAP_adr_legacy_fm: -0.0137 [-0.0245, -0.0017] -> harmful
RQ1 PortoAlegre_2024 R4_+forcing info_nats_fm: +0.0002 [-0.0005, +0.0007] -> inconclusive
RQ1 PortoAlegre_2024 R4_+forcing info_frac_fm: +0.0008 [-0.0020, +0.0030] -> saturated | reading: equivalent to zero (within SESOI)
RQ1 PortoAlegre_2024 R4_+forcing dAP_stacked_fm: +0.0001 [-0.0004, +0.0004] -> saturated | reading: equivalent to zero (within SESOI)
RQ1 PortoAlegre_2024 R4_+forcing dAP_gated_fm: +0.0001 [+0.0001, +0.0001] -> saturated | reading: equivalent to zero (within SESOI)
RQ1 PortoAlegre_2024 R4_+forcing dAP_early_fm: -0.0001 [-0.0026, +0.0015] -> saturated | reading: equivalent to zero (within SESOI)
RQ1 PortoAlegre_2024 R4_+forcing dAP_adr_legacy_fm: -0.0964 [-0.1121, -0.0768] -> harmful
RQ1 TaquariValley_2024 R4_+forcing info_nats_fm: -0.0123 [-0.0319, +0.0030] -> inconclusive
RQ1 TaquariValley_2024 R4_+forcing info_frac_fm: -0.0543 [-0.1268, +0.0181] -> inconclusive
RQ1 TaquariValley_2024 R4_+forcing dAP_stacked_fm: -0.0111 [-0.0311, +0.0420] -> inconclusive
RQ1 TaquariValley_2024 R4_+forcing dAP_gated_fm: -0.0322 [-0.0349, +0.0250] -> inconclusive
RQ1 TaquariValley_2024 R4_+forcing dAP_early_fm: +0.0137 [-0.0102, +0.0354] -> inconclusive
RQ1 TaquariValley_2024 R4_+forcing dAP_adr_legacy_fm: -0.0202 [-0.0378, -0.0043] -> harmful
RQ1 Valencia_2024 R5_+sar_event info_nats_fm: +0.0752 [-0.0245, +0.1713] -> inconclusive
RQ1 Valencia_2024 R5_+sar_event info_frac_fm: +0.1758 [-0.0772, +0.3310] -> inconclusive
RQ1 Valencia_2024 R5_+sar_event dAP_stacked_fm: +0.0382 [-0.0033, +0.1030] -> inconclusive
RQ1 Valencia_2024 R5_+sar_event dAP_gated_fm: -0.0123 [-0.0324, +0.0277] -> inconclusive
RQ1 Valencia_2024 R5_+sar_event dAP_early_fm: -0.0048 [-0.0249, +0.0811] -> inconclusive
RQ1 Valencia_2024 R5_+sar_event dAP_adr_legacy_fm: -0.1236 [-0.1481, -0.0517] -> harmful
RQ1 York_2015 R5_+sar_event info_nats_fm: +0.0369 [+0.0055, +0.0551] -> inconclusive | no evaluable social layer
RQ1 York_2015 R5_+sar_event info_frac_fm: +0.1441 [+0.0275, +0.2398] -> inconclusive | no evaluable social layer
RQ1 York_2015 R5_+sar_event dAP_stacked_fm: +0.0332 [+0.0215, +0.0662] -> inconclusive | no evaluable social layer
RQ1 York_2015 R5_+sar_event dAP_gated_fm: +0.0054 [-0.0232, +0.0215] -> inconclusive | no evaluable social layer
RQ1 York_2015 R5_+sar_event dAP_early_fm: -0.0104 [-0.0343, +0.0377] -> inconclusive | no evaluable social layer
RQ1 York_2015 R5_+sar_event dAP_adr_legacy_fm: -0.1361 [-0.2002, -0.0153] -> harmful | no evaluable social layer

Placebo Carlisle_2015 info_nats_fm_adj: real slope -0.0999 vs population-density slope -0.3003; Spearman(social, population) 0.99; social gain with population controlled at top rung +0.0250 [-0.4819, +0.5806] inconclusive
Placebo Carlisle_2015 dAP_stacked_fm_adj: real slope +0.2059 vs population-density slope +0.1926; Spearman(social, population) 0.99; social gain with population controlled at top rung +0.0081 [-0.0139, +0.0520] inconclusive
Placebo Chennai_2015 info_nats_fm_adj: real slope -0.0306 vs population-density slope -0.0924; Spearman(social, population) 0.80; social gain with population controlled at top rung -0.0022 [-0.0225, +0.0132] saturated
Placebo Chennai_2015 dAP_stacked_fm_adj: real slope -0.2943 vs population-density slope -0.5575; Spearman(social, population) 0.80; social gain with population controlled at top rung -0.0057 [-0.0269, +0.0147] inconclusive
Placebo EmiliaRomagna_2023a info_nats_fm_adj: real slope +0.0827 vs population-density slope +0.0517; Spearman(social, population) 0.82; social gain with population controlled at top rung +0.0279 [-0.0622, +0.1301] inconclusive
Placebo EmiliaRomagna_2023a dAP_stacked_fm_adj: real slope -0.1587 vs population-density slope -0.0429; Spearman(social, population) 0.82; social gain with population controlled at top rung -0.0527 [-0.0751, +0.1062] inconclusive
Placebo Forli_2023b info_nats_fm_adj: real slope +0.0039 vs population-density slope +0.0092; Spearman(social, population) 0.24; social gain with population controlled at top rung +0.0067 [-0.0024, +0.0160] saturated
Placebo Forli_2023b dAP_stacked_fm_adj: real slope +0.0452 vs population-density slope +0.0100; Spearman(social, population) 0.24; social gain with population controlled at top rung +0.0046 [-0.0032, +0.0141] inconclusive
Placebo Houston_SanJacinto_2017 info_nats_fm_adj: real slope +0.0049 vs population-density slope +0.0012; Spearman(social, population) 0.45; social gain with population controlled at top rung +0.0060 [+0.0018, +0.0105] saturated
Placebo Houston_SanJacinto_2017 dAP_stacked_fm_adj: real slope -0.0212 vs population-density slope +0.0235; Spearman(social, population) 0.45; social gain with population controlled at top rung +0.0032 [+0.0008, +0.0059] saturated
Placebo Jakarta_2020 info_nats_fm_adj: real slope +0.0190 vs population-density slope -0.0067; Spearman(social, population) 0.76; social gain with population controlled at top rung -0.0102 [-0.0240, +0.0046] inconclusive
Placebo Jakarta_2020 dAP_stacked_fm_adj: real slope +0.1739 vs population-density slope -0.0750; Spearman(social, population) 0.76; social gain with population controlled at top rung -0.0186 [-0.0344, +0.0010] inconclusive
Placebo PortoAlegre_2024 info_nats_fm_adj: real slope -0.0003 vs population-density slope +0.0407; Spearman(social, population) 0.51; social gain with population controlled at top rung +0.0008 [-0.0020, +0.0029] saturated
Placebo PortoAlegre_2024 dAP_stacked_fm_adj: real slope +0.1030 vs population-density slope -0.0025; Spearman(social, population) 0.51; social gain with population controlled at top rung +0.0001 [-0.0004, +0.0005] saturated
Placebo TaquariValley_2024 info_nats_fm_adj: real slope -0.0365 vs population-density slope +0.0003; Spearman(social, population) 0.91; social gain with population controlled at top rung -0.0651 [-0.1489, +0.0115] inconclusive
Placebo TaquariValley_2024 dAP_stacked_fm_adj: real slope -0.0152 vs population-density slope +0.1119; Spearman(social, population) 0.91; social gain with population controlled at top rung -0.0122 [-0.0350, +0.0336] inconclusive
Placebo Valencia_2024 info_nats_fm_adj: real slope +0.0239 vs population-density slope -0.0822; Spearman(social, population) 0.70; social gain with population controlled at top rung +0.1813 [-0.0885, +0.3426] inconclusive
Placebo Valencia_2024 dAP_stacked_fm_adj: real slope -0.2227 vs population-density slope +0.0275; Spearman(social, population) 0.70; social gain with population controlled at top rung +0.0422 [-0.0017, +0.1094] inconclusive
Placebo York_2015 info_nats_fm_adj: real slope +0.0379 vs population-density slope +0.0308; Spearman(social, population) 0.49; social gain with population controlled at top rung +0.1434 [+0.0257, +0.2435] inconclusive
Placebo York_2015 dAP_stacked_fm_adj: real slope +0.1095 vs population-density slope -0.1614; Spearman(social, population) 0.49; social gain with population controlled at top rung +0.0291 [+0.0154, +0.0650] inconclusive

## Post-hoc robustness and diagnostics (v6.1.2; not pre-registered, never a headline)
Robustness (post hoc) top-rung dAP_stacked_fm: all confirmatory cities: +0.0021 [-0.0023, +0.0065] k=9; one estimate per disaster: +0.0022 [-0.0029, +0.0073] k=7; without disaster EmiliaRomagna_May2023 (EmiliaRomagna_2023a,Forli_2023b): +0.0021 [-0.0038, +0.0081] k=7; without disaster RioGrandeDoSul_May2024 (PortoAlegre_2024,TaquariValley_2024): +0.0062 [-0.0060, +0.0185] k=7; without events whose CV block is shorter than the label range: +0.0032 [-0.0009, +0.0074] k=6
Robustness (post hoc) top-rung dAP_adr_legacy_fm: all confirmatory cities: -0.0716 [-0.1112, -0.0320] k=9; one estimate per disaster: -0.0772 [-0.1274, -0.0271] k=7; without disaster EmiliaRomagna_May2023 (EmiliaRomagna_2023a,Forli_2023b): -0.0830 [-0.1362, -0.0298] k=7; without disaster RioGrandeDoSul_May2024 (PortoAlegre_2024,TaquariValley_2024): -0.0775 [-0.1292, -0.0257] k=7; without events whose CV block is shorter than the label range: -0.0528 [-0.1032, -0.0024] k=6
Robustness (post hoc) gradient slope info_nats_fm_adj: all confirmatory cities: +0.0042 [-0.0001, +0.0085] k=9; one estimate per disaster: +0.0042 [-0.0004, +0.0088] k=7; without disaster EmiliaRomagna_May2023 (EmiliaRomagna_2023a,Forli_2023b): +0.0043 [-0.0016, +0.0101] k=7; without disaster RioGrandeDoSul_May2024 (PortoAlegre_2024,TaquariValley_2024): +0.0047 [-0.0001, +0.0094] k=7; without events whose CV block is shorter than the label range: +0.0044 [-0.0010, +0.0099] k=6
CV block shorter than the label's autocorrelation range: Carlisle_2015, PortoAlegre_2024, Valencia_2024
Calibration (post hoc, fold mean, top rung) physical: median ECE 0.061, median calibration slope 0.67 over 10 cities
Calibration (post hoc, fold mean, top rung) recal_R: median ECE 0.059, median calibration slope 1.55 over 10 cities
Calibration (post hoc, fold mean, top rung) stacked_RS: median ECE 0.060, median calibration slope 1.13 over 10 cities
Null correction: 6 of 60 top-rung verdicts differ from the archived run d55d6b06 (v6.1.1 null, masked cells set to 0); see T14
