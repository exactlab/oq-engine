import os
import unittest
import tempfile
import shutil
import zipfile
from openquake.risklib.readers import read_calculator_input, Archive


TEST_FRAGILITY = '''\
'continuous'	{'IMT': 'PGA', 'imls': None}	['slight', 'moderate', 'extensive', 'complete']
'W'	[(0.147, 0.414), (0.236, 0.666), (0.416, 1.172), (0.627, 1.77)]	None
'A'	[(0.122, 0.345), (0.171, 0.483), (0.236, 0.666), (0.383, 1.08)]	None
'DS'	[(0.081, 0.23), (0.122, 0.345), (0.228, 0.643), (0.326, 0.919)]	None
'UFB'	[(0.114, 0.322), (0.171, 0.483), (0.326, 0.919), (0.489, 1.379)]	None
'RC'	[(0.13, 0.368), (0.187, 0.529), (0.334, 0.942), (0.627, 1.77)]	None
'''

TEST_VULNERABILITY = '''\
'W'	'PGA'	[0.01, 0.06, 0.11, 0.16, 0.21, 0.26, 0.31, 0.36, 0.41, 0.46, 0.51, 0.56, 0.61, 0.66, 0.71, 0.76, 0.81, 0.86, 0.91, 0.96, 1.01, 1.06, 1.11, 1.16, 1.21, 1.26, 1.31, 1.36, 1.41, 1.46]	[6.88403e-08, 0.001595496, 0.013508641, 0.040191158, 0.080174564, 0.12987209, 0.185478238, 0.243763275, 0.302283223, 0.359329841, 0.413793327, 0.465015667, 0.512663741, 0.556629259, 0.596953791, 0.63377442, 0.667285292, 0.697710983, 0.725288448, 0.750255091, 0.772841156, 0.793265105, 0.811731071, 0.828427693, 0.843527877, 0.857189145, 0.869554353, 0.880752611, 0.890900313, 0.900102185]	[0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3]	'LN'
'A'	'PGA'	[0.01, 0.06, 0.11, 0.16, 0.21, 0.26, 0.31, 0.36, 0.41, 0.46, 0.51, 0.56, 0.61, 0.66, 0.71, 0.76, 0.81, 0.86, 0.91, 0.96, 1.01, 1.06, 1.11, 1.16, 1.21, 1.26, 1.31, 1.36, 1.41, 1.46]	[3.39926e-07, 0.006623843, 0.050557647, 0.131254324, 0.228841325, 0.328190116, 0.421201301, 0.50444515, 0.577064937, 0.639478485, 0.692657584, 0.737750901, 0.775897604, 0.808143263, 0.835409033, 0.858487537, 0.878051212, 0.894665685, 0.908804349, 0.920862323, 0.931169015, 0.93999901, 0.94758135, 0.954107302, 0.959736836, 0.964603981, 0.968821258, 0.972483321, 0.975669973, 0.978448638]	[0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3]	'LN'
'''

TEST_EXPOSURE = '''\
83.313823	29.461172	a1	1.0	W
83.313823	29.236172	a2	1.0	W
83.538823	29.086172	a3	1.0	W
80.688823	28.936172	a4	1.0	W
83.538823	29.011172	a5	1.0	W
81.138823	28.786172	a6	1.0	W
83.988823	28.486172	a7	1.0	W
83.238823	29.386172	a8	1.0	W
83.013823	29.086172	a9	1.0	W
83.313823	28.711172	a10	1.0	W
86.913823	27.736172	a11	1.0	W
83.163823	29.311172	a12	1.0	W
80.613823	28.936172	a13	1.0	W
83.913823	29.011172	a14	1.0	W
82.038823	30.286172	a15	1.0	W
83.388823	29.311172	a16	1.0	W
80.688823	28.861172	a17	1.0	W
83.463823	28.711172	a18	1.0	W
84.138823	28.411172	a19	1.0	W
83.088823	29.161172	a20	1.0	W
84.138823	28.786172	a21	1.0	W
85.113823	28.336172	a22	1.0	W
84.063823	29.011172	a23	1.0	W
83.013823	29.611172	a24	1.0	W
86.838823	27.736172	a25	2.0	W
84.363823	28.786172	a26	2.0	W
84.138823	28.561172	a27	2.0	W
83.163823	29.011172	a28	2.0	W
83.013823	29.236172	a29	2.0	W
82.863823	28.861172	a30	2.0	W
85.038823	28.561172	a31	2.0	W
86.088823	28.036172	a32	2.0	W
83.313823	28.786172	a33	2.0	W
81.888823	28.186172	a34	2.0	W
83.238823	29.311172	a35	2.0	W
84.138823	29.161172	a36	2.0	W
84.213823	28.786172	a37	2.0	W
'''


# 12 sites, 10 realizations each
TEST_GMF = '''\
81.1360288452	31.601922511	0.0155109509698	0.00281034507007	0.006137162745	0.00454256869266	0.00841536691411	0.00815489110943	0.00254942300302	0.0101655147721	0.00944116473873	0.0094607789499
81.1677059042	31.601922511	0.00899057046441	0.00405841972037	0.00441534148331	0.00529987234583	0.00334456852911	0.0221581127201	0.00660507453023	0.00840619504425	0.0105270002691	0.0116465013536
81.1993829633	31.701922511	0.0105041752935	0.0108706808919	0.0037678053978	0.0105597140166	0.00442298626614	0.0153968883449	0.00489369708777	0.0174061610838	0.0103710312376	0.0254641145336
81.2310600223	31.801922511	0.0038314949803	0.00701340019108	0.00401934628066	0.00276358630792	0.00624378179609	0.0335800686421	0.0172930286757	0.0206501711555	0.00753954561238	0.0072787269004
81.2627370814	31.901922511	0.0128910667848	0.00580351154962	0.00388071555435	0.00238070724146	0.00546143484763	0.0104924694544	0.00532817103564	0.0170757540609	0.0124151013776	0.00377333270407
81.2944141404	30.601922511	0.012519733433	0.0057127539192	0.00453065872893	0.00949023614394	0.00636330038807	0.00735163083445	0.00925537617681	0.0275380124595	0.0114083376694	0.00465955611959
81.3260911994	30.601922511	0.0045877936891	0.0147964518058	0.00322050382136	0.00814347439692	0.00716796830064	0.0103024384277	0.00981195819997	0.0177419573727	0.0125670163171	0.0101488439452
81.3577682585	30.701922511	0.0102443105402	0.00606207129316	0.00823714945475	0.00524593011434	0.00540979277623	0.010082922739	0.00784231206331	0.0101236254072	0.0190497345128	0.00805915211349
81.3894453175	30.801922511	0.00654663652265	0.0095964929733	0.0122152562482	0.00834771864269	0.00570107753851	0.0126915283663	0.0109467946063	0.0143932147114	0.0121319515459	0.00539985982664
81.4211223766	30.901922511	0.012959412241	0.00354379598578	0.00646797082495	0.0108914758967	0.00545189598765	0.00799026400705	0.01864942028	0.0323645600851	0.00352523429059	0.00610965297776
81.4527994356	31.101922511	0.0187101169056	0.00840790036664	0.00623415340343	0.010885256269	0.00439819502041	0.0206557263556	0.0132246632429	0.014605474028	0.00519319743559	0.0164983082137
81.4844764947	31.201922511	0.0111324218367	0.00665166335463	0.00481592358942	0.0151723816152	0.0092773187225	0.0171059289499	0.00777314631674	0.0122995131714	0.0131377292775	0.00887701181102
'''


class TestIO(unittest.TestCase):
    FILETYPES = 'FRAGILITY VULNERABILITY EXPOSURE GMF'.split()

    def setUp(self):
        # create a temporary directory with different input files
        self.path = tempfile.mkdtemp()
        self.archive = Archive(self.path)

    def writefiles(self, ext):
        with self.archive.open('job.ini', 'w') as ini:
            ini.write('[general]\n')
            for ftype in self.FILETYPES:
                ini.write('%s_file=%s%s\n' % (ftype, ftype, ext))
                with self.archive.open(ftype + ext, 'w') as f:
                    f.write(globals()['TEST_%s' % ftype])

    def test_read_csv_files(self):
        self.writefiles('.csv')
        inp = read_calculator_input(self.path)
        self.assertEqual(len(inp['fragility']), 5)
        self.assertEqual(len(inp['vulnerability']), 2)
        self.assertEqual(len(inp['exposure']), 37)
        self.assertEqual(len(inp['gmf']), 12)

    def test_read_csv_gz_files(self):
        self.writefiles('.csv.gz')
        inp = read_calculator_input(self.path)
        self.assertEqual(len(inp['fragility']), 5)
        self.assertEqual(len(inp['vulnerability']), 2)
        self.assertEqual(len(inp['exposure']), 37)
        self.assertEqual(len(inp['gmf']), 12)

    def test_read_zip_file(self):
        self.writefiles('.csv')
        path = self.path + '.zip'
        zfile = zipfile.ZipFile(path, 'w')
        zfile.write(os.path.join(self.path, 'job.ini'), 'job.ini')
        for ftype in self.FILETYPES:
            zfile.write(os.path.join(self.path, ftype + '.csv'),
                        ftype + '.csv')
        zfile.close()
        inp = read_calculator_input(path)
        self.assertEqual(len(inp['fragility']), 5)
        self.assertEqual(len(inp['vulnerability']), 2)
        self.assertEqual(len(inp['exposure']), 37)
        self.assertEqual(len(inp['gmf']), 12)

    def tearDown(self):
        # remove the directory
        shutil.rmtree(self.path)
