from pathlib import Path
from dotenv import load_dotenv
import os


# load env variables, for DATA_DIR
dotenv_path = Path().absolute() / '.env'
if dotenv_path.exists():
    load_dotenv(dotenv_path)


import pandas as pd
import cv2
import pydicom as dicom
import numpy as np
import random
from shutil import copyfile

from covid_xrays_model import config


np.random.seed(config.SEED)

"""
Assuming data is downloaded, and unziped

git clone https://github.com/ieee8023/covid-chestxray-dataset.git
git clone https://github.com/agchung/Figure1-COVID-chestxray-dataset.git
git clone https://github.com/agchung/Actualmed-COVID-chestxray-dataset.git

kaggle datasets download tawsifurrahman/covid19-radiography-database
kaggle competitions download rsna-pneumonia-detection-challenge

create train and test dir inside processed
"""

# parameters for COVIDx dataset
train = []
test = []
test_count = {'normal': 0, 'pneumonia': 0, 'COVID-19': 0}
train_count = {'normal': 0, 'pneumonia': 0, 'COVID-19': 0}

mapping = dict()
mapping['COVID-19'] = 'COVID-19'
mapping['SARS'] = 'pneumonia'
mapping['MERS'] = 'pneumonia'
mapping['Streptococcus'] = 'pneumonia'
mapping['Klebsiella'] = 'pneumonia'
mapping['Chlamydophila'] = 'pneumonia'
mapping['Legionella'] = 'pneumonia'
mapping['Normal'] = 'normal'
mapping['Lung Opacity'] = 'pneumonia'
mapping['1'] = 'pneumonia'

# train/test split
split = 0.1

# to avoid duplicates
patient_imgpath = {}


# adapted from https://github.com/mlmed/torchxrayvision/blob/master/torchxrayvision/datasets.py#L814
cohen_csv = pd.read_csv(config.cohen_csvpath, nrows=None)
#idx_pa = csv["view"] == "PA"  # Keep only the PA view
views = ["PA", "AP", "AP Supine", "AP semi erect", "AP erect"]
cohen_idx_keep = cohen_csv.view.isin(views)
cohen_csv = cohen_csv[cohen_idx_keep]

fig1_csv = pd.read_csv(config.fig1_csvpath, encoding='ISO-8859-1', nrows=None)
actmed_csv = pd.read_csv(config.actmed_csvpath, nrows=None)

sirm_csv = pd.read_excel(config.sirm_csvpath)


# get non-COVID19 viral, bacteria, and COVID-19 infections from covid-chestxray-dataset, figure1 and actualmed
# stored as patient id, image filename and label
filename_label = {'normal': [], 'pneumonia': [], 'COVID-19': []}
count = {'normal': 0, 'pneumonia': 0, 'COVID-19': 0}
covid_ds = {'cohen': [], 'fig1': [], 'actmed': [], 'sirm': []}

for index, row in cohen_csv.iterrows():
    f = row['finding'].split(',')[0] # take the first finding, for the case of COVID-19, ARDS
    if f in mapping: #
        count[mapping[f]] += 1
        entry = [str(row['patientid']), row['filename'], mapping[f], 'cohen']
        filename_label[mapping[f]].append(entry)
        if mapping[f] == 'COVID-19':
            covid_ds['cohen'].append(str(row['patientid']))

for index, row in fig1_csv.iterrows():
    if not str(row['finding']) == 'nan':
        f = row['finding'].split(',')[0] # take the first finding
        if f in mapping: #
            count[mapping[f]] += 1
            if os.path.exists(os.path.join(config.fig1_imgpath, row['patientid'] + '.jpg')):
                entry = [row['patientid'], row['patientid'] + '.jpg', mapping[f], 'fig1']
            elif os.path.exists(os.path.join(config.fig1_imgpath, row['patientid'] + '.png')):
                entry = [row['patientid'], row['patientid'] + '.png', mapping[f], 'fig1']
            filename_label[mapping[f]].append(entry)
            if mapping[f] == 'COVID-19':
                covid_ds['fig1'].append(row['patientid'])

for index, row in actmed_csv.iterrows():
    if not str(row['finding']) == 'nan':
        f = row['finding'].split(',')[0]
        if f in mapping:
            count[mapping[f]] += 1
            entry = [row['patientid'], row['imagename'], mapping[f], 'actmed']
            filename_label[mapping[f]].append(entry)
            if mapping[f] == 'COVID-19':
                covid_ds['actmed'].append(row['patientid'])

sirm = set(sirm_csv['URL'])
cohen = set(cohen_csv['url'])
discard = ['100', '101', '102', '103', '104', '105',
           '110', '111', '112', '113', '122', '123',
           '124', '125', '126', '217']

for idx, row in sirm_csv.iterrows():
    patientid = row['FILE NAME']
    if row['URL'] not in cohen and patientid[patientid.find('(')+1:patientid.find(')')] not in discard:
        count[mapping['COVID-19']] += 1
        imagename = patientid + '.' + row['FORMAT'].lower()
        if not os.path.exists(os.path.join(config.sirm_imgpath, imagename)):
            imagename = patientid.split('(')[0] + ' ('+ patientid.split('(')[1] + '.' + row['FORMAT'].lower()
        entry = [patientid, imagename, mapping['COVID-19'], 'sirm']
        filename_label[mapping['COVID-19']].append(entry)
        covid_ds['sirm'].append(patientid)

print('Data distribution from covid datasets:')
print(count)


# add covid-chestxray-dataset, figure1 and actualmed into COVIDx dataset
# since these datasets don't have test dataset, split into train/test by patientid
# for covid-chestxray-dataset:
# patient 8 is used as non-COVID19 viral test
# patient 31 is used as bacterial test
# patients 19, 20, 36, 42, 86 are used as COVID-19 viral test
# for figure 1:
# patients 24, 25, 27, 29, 30, 32, 33, 36, 37, 38

ds_imgpath = {'cohen': config.cohen_imgpath, 'fig1': config.fig1_imgpath, 'actmed':
              config.actmed_imgpath, 'sirm': config.sirm_imgpath}

for key in filename_label.keys():
    arr = np.array(filename_label[key])
    if arr.size == 0:
        continue
    # split by patients
    # num_diff_patients = len(np.unique(arr[:,0]))
    # num_test = max(1, round(split*num_diff_patients))
    # select num_test number of random patients
    # random.sample(list(arr[:,0]), num_test)
    if key == 'pneumonia':
        test_patients = ['8', '31']
    elif key == 'COVID-19':
        test_patients = ['19', '20', '36', '42', '86',
                         '94', '97', '117', '132',
                         '138', '144', '150', '163', '169', '174', '175', '179', '190', '191'
                         'COVID-00024', 'COVID-00025', 'COVID-00026', 'COVID-00027', 'COVID-00029',
                         'COVID-00030', 'COVID-00032', 'COVID-00033', 'COVID-00035', 'COVID-00036',
                         'COVID-00037', 'COVID-00038',
                         'ANON24', 'ANON45', 'ANON126', 'ANON106', 'ANON67',
                         'ANON153', 'ANON135', 'ANON44', 'ANON29', 'ANON201',
                         'ANON191', 'ANON234', 'ANON110', 'ANON112', 'ANON73',
                         'ANON220', 'ANON189', 'ANON30', 'ANON53', 'ANON46',
                         'ANON218', 'ANON240', 'ANON100', 'ANON237', 'ANON158',
                         'ANON174', 'ANON19', 'ANON195',
                         'COVID-19(119)', 'COVID-19(87)', 'COVID-19(70)', 'COVID-19(94)',
                         'COVID-19(215)', 'COVID-19(77)', 'COVID-19(213)', 'COVID-19(81)',
                         'COVID-19(216)', 'COVID-19(72)', 'COVID-19(106)', 'COVID-19(131)',
                         'COVID-19(107)', 'COVID-19(116)', 'COVID-19(95)', 'COVID-19(214)',
                         'COVID-19(129)']
    else:
        test_patients = []
    print('Key: ', key)
    print('Test patients: ', test_patients)
    # go through all the patients
    for patient in arr:
        if patient[0] not in patient_imgpath:
            patient_imgpath[patient[0]] = [patient[1]]
        else:
            if patient[1] not in patient_imgpath[patient[0]]:
                patient_imgpath[patient[0]].append(patient[1])
            else:
                continue  # skip since image has already been written
        if patient[0] in test_patients:
            if patient[3] == 'sirm':
                image = cv2.imread(os.path.join(ds_imgpath[patient[3]], patient[1]))
                gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
                patient[1] = patient[1].replace(' ', '')
                cv2.imwrite(os.path.join(config.PROCESSED_DATA_DIR, 'test', patient[1]), gray)
            else:
                copyfile(os.path.join(ds_imgpath[patient[3]], patient[1]), os.path.join(config.PROCESSED_DATA_DIR, 'test', patient[1]))
            test.append(patient)
            test_count[patient[2]] += 1
        else:
            if patient[3] == 'sirm':
                image = cv2.imread(os.path.join(ds_imgpath[patient[3]], patient[1]))
                gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
                patient[1] = patient[1].replace(' ', '')
                cv2.imwrite(os.path.join(config.PROCESSED_DATA_DIR, 'train', patient[1]), gray)
            else:
                copyfile(os.path.join(ds_imgpath[patient[3]], patient[1]), os.path.join(config.PROCESSED_DATA_DIR, 'train', patient[1]))
            train.append(patient)
            train_count[patient[2]] += 1

print('test count: ', test_count)
print('train count: ', train_count)


# add normal and rest of pneumonia cases from https://www.kaggle.com/c/rsna-pneumonia-detection-challenge
csv_normal = pd.read_csv(config.rsna_csvname, nrows=None)
csv_pneu = pd.read_csv(config.rsna_csvname2, nrows=None)
patients = {'normal': [], 'pneumonia': []}

for index, row in csv_normal.iterrows():
    if row['class'] == 'Normal':
        patients['normal'].append(row['patientId'])

for index, row in csv_pneu.iterrows():
    if int(row['Target']) == 1:
        patients['pneumonia'].append(row['patientId'])

for key in patients.keys():
    arr = np.array(patients[key])
    if arr.size == 0:
        continue
    # split by patients
    # num_diff_patients = len(np.unique(arr))
    # num_test = max(1, round(split*num_diff_patients))
    test_patients = np.load(config.RAW_DATA_DIR / 'rsna_test_patients_{}.npy'.format(key)) # random.sample(list(arr), num_test), download the .npy files from the repo.
    # np.save('rsna_test_patients_{}.npy'.format(key), np.array(test_patients))
    for patient in arr:
        if patient not in patient_imgpath:
            patient_imgpath[patient] = [patient]
        else:
            continue  # skip since image has already been written

        ds = dicom.dcmread(os.path.join(config.rsna_imgpath, patient + '.dcm'))
        pixel_array_numpy = ds.pixel_array
        imgname = patient + '.png'
        if patient in test_patients:
            cv2.imwrite(os.path.join(config.PROCESSED_DATA_DIR, 'test', imgname), pixel_array_numpy)
            test.append([patient, imgname, key, 'rsna'])
            test_count[key] += 1
        else:
            cv2.imwrite(os.path.join(config.PROCESSED_DATA_DIR, 'train', imgname), pixel_array_numpy)
            train.append([patient, imgname, key, 'rsna'])
            train_count[key] += 1

print('test count: ', test_count)
print('train count: ', train_count)


# final stats
print('Final stats')
print('Train count: ', train_count)
print('Test count: ', test_count)
print('Total length of train: ', len(train))
print('Total length of test: ', len(test))


# export to train and test csv
# format as patientid, filename, label, separated by a space
train_file = open(config.PROCESSED_DATA_DIR / "train_split_v3.txt",'w')
for sample in train:
    if len(sample) == 4:
        info = str(sample[0]) + ' ' + sample[1] + ' ' + sample[2] + ' ' + sample[3] + '\n'
    else:
        info = str(sample[0]) + ' ' + sample[1] + ' ' + sample[2] + '\n'
    train_file.write(info)

train_file.close()

test_file = open(config.PROCESSED_DATA_DIR / "test_split_v3.txt", 'w')
for sample in test:
    if len(sample) == 4:
        info = str(sample[0]) + ' ' + sample[1] + ' ' + sample[2] + ' ' + sample[3] + '\n'
    else:
        info = str(sample[0]) + ' ' + sample[1] + ' ' + sample[2] + '\n'
    test_file.write(info)

test_file.close()


# Save labels file

labels_train = pd.read_csv(config.PROCESSED_DATA_DIR / "train_split_v3.txt", header=None, sep=' ',
                          names=['patient', 'name', 'label', 'dataset'])
labels_train.name = 'train/' + labels_train.name
labels_train['ds_type'] = 'train'

labels_test = pd.read_csv(config.PROCESSED_DATA_DIR / "test_split_v3.txt", header=None, sep=' ',
                          names=['patient', 'name', 'label', 'dataset'])
labels_test.name = 'test/' + labels_test.name
labels_test['ds_type'] = 'test'

all_labels = pd.concat([labels_train, labels_test])

all_labels[['name', 'label']].to_csv(config.PROCESSED_DATA_DIR / 'labels.csv', index=False)
all_labels.to_csv(config.PROCESSED_DATA_DIR / 'labels_full.csv', index=False)

print(all_labels.head())



