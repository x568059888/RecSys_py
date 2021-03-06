#! -*- coding: utf-8 -*-

"""
    train: --train true --train_set ../dataset/rec_train_set.sample.txt --validation_set ../dataset/rec_validation_set.sample.txt --model_type 2 --batch_size 128 --train_epochs 100 --train_steps_per_epoch 20 --validation_steps 50 --early_stop_patience 5 --lr_per_step 1000 --d_feature 19 --saved_model_name ../trained_model/PRM_model.h5
    predict: --test_set ../dataset/rec_test_set.sample.txt --batch_size 2 --model_type 2 --saved_model_name ../trained_model/PRM_model.h5 --d_feature 19
    evaluate: ../dataset/rec_test_set.sample.txt.predict.out
"""
from __future__ import absolute_import, division, print_function

from abc import ABC

from tensorflow.python.keras.callbacks import Callback, TensorBoard, ModelCheckpoint, EarlyStopping
from tensorflow.python.keras.losses import categorical_crossentropy, Loss
from tensorflow.python.keras.optimizer_v2.adam import Adam
from tensorflow.python.keras.optimizer_v2.learning_rate_schedule import LearningRateSchedule

from PRM import *

import numpy as np
import time
import json
import os

tf.compat.v1.disable_eager_execution()
tf.compat.v1.experimental.output_all_intermediates(True)

tf.compat.v1.flags.DEFINE_boolean("train", False, "train or predict")
# params setting
tf.compat.v1.flags.DEFINE_string("train_set", "", "the file path of train set")
tf.compat.v1.flags.DEFINE_string("validation_set", "", "the file path of validation set")
tf.compat.v1.flags.DEFINE_string("test_set", "", "the file path of test set")
# tf.compat.v1.flags.DEFINE_string("log_dir", "./log/", "the log directory")
tf.compat.v1.flags.DEFINE_string("saved_model_name", "drr_model.h5", "the saved model name")
tf.compat.v1.flags.DEFINE_integer("model_type", 0,
                                  "drr model type, 0:drr_base 1:drr_personalized_v1 2:drr_personalized_v2")
tf.compat.v1.flags.DEFINE_integer("batch_size", 512, "batch size for training")
tf.compat.v1.flags.DEFINE_integer("seq_len", 30, "the length of input list")
tf.compat.v1.flags.DEFINE_integer("train_epochs", 100, "epoch for training")
tf.compat.v1.flags.DEFINE_integer("train_steps_per_epoch", 1000, "steps per epoch for training")
tf.compat.v1.flags.DEFINE_integer("validation_steps", 2000, "steps for validation")
tf.compat.v1.flags.DEFINE_integer("early_stop_patience", 10, "early stop when model is not improved with X epochs")
tf.compat.v1.flags.DEFINE_integer("lr_per_step", 4000, "update learning rate per X step")

tf.compat.v1.flags.DEFINE_integer("d_feature", 7, "the feature length of each item in the input list")
tf.compat.v1.flags.DEFINE_integer("d_model", 64, "param used drr_model")
tf.compat.v1.flags.DEFINE_integer("d_inner_hid", 128, "param used in drr_model")
tf.compat.v1.flags.DEFINE_integer("n_head", 1, "param used in drr_model")
tf.compat.v1.flags.DEFINE_integer("d_k", 64, "param used in drr_model")
tf.compat.v1.flags.DEFINE_integer("d_v", 64, "param used in drr_model")
tf.compat.v1.flags.DEFINE_integer("n_layers", 2, "param used in drr_model")
tf.compat.v1.flags.DEFINE_float("dropout", 0.1, "param used in drr_model")

FLAGS = tf.compat.v1.flags.FLAGS

FEATURE_INFO_MAP = {
    "icf": ['icf1', 'icf2', 'icf3', 'icf4', 'icf5'],
    "ucf": ['ucf1', 'ufc2', 'ucf3'],
    "pv": ['iv1', 'iv2', 'iv3', 'iv4', 'iv5', 'iv6', 'iv7', 'iv8', 'iv9', 'iv10', 'iv11', 'iv12'],
    "iv": ['pv1', 'pv2', 'pv3', 'pv4', 'pv5', 'pv6', 'pv7'],
    "iv+pv": ['iv1', 'iv2', 'iv3', 'iv4', 'iv5', 'iv6', 'iv7', 'iv8', 'iv9', 'iv10', 'iv11', 'iv12', 'pv1', 'pv2',
              'pv3', 'pv4', 'pv5', 'pv6', 'pv7']
}

"""

@:return outputs
    *shape: [batch_size * seq_len]
    [
        [0, 1, 2, ... , seq_len - 1],
        ...
    ]
"""


# get position
def get_pos(batch_size, seq_len):
    outputs = np.zeros((batch_size, seq_len), dtype=np.int32)
    for i in range(batch_size):
        outputs[i] = np.arange(seq_len, dtype=np.int32)
    return outputs


# get label from raw input batch
def get_label(label_batch, batch_size, seq_len):
    outputs = np.zeros((batch_size, seq_len))
    i = 0
    for row in label_batch:
        outputs[i] = np.array(json.loads(row))
        i += 1
    return outputs


# get uid from raw input batch
def get_uid(features_batch, batch_size, seq_len):
    outputs = np.zeros((batch_size, seq_len), dtype=np.int32)
    i = 0
    for uid in features_batch:
        outputs[i] = np.array([uid] * seq_len, dtype=np.int32)
        i += 1
    return outputs


# get icf from raw input batch
def get_icf(features_batch, batch_size, seq_len):
    global FEATURE_INFO_MAP
    feature_len = len(FEATURE_INFO_MAP["icf"])
    outputs = []
    for i in range(feature_len):
        outputs.append(np.zeros((batch_size, seq_len), dtype=np.int32))
    j = 0
    for row in features_batch:
        feature_data = np.array(json.loads(row), dtype=np.int32).T
        for i in range(feature_len):
            outputs[i][j] = feature_data[i, :]
        j += 1
    return outputs


# get ucf from raw input batch
def get_ucf(features_batch, batch_size, seq_len):
    global FEATURE_INFO_MAP
    feature_len = len(FEATURE_INFO_MAP['ucf'])
    outputs = []
    for i in range(feature_len):
        outputs.append(np.zeros((batch_size, seq_len), dtype=np.int32))
    j = 0
    for row in features_batch:
        feature_data = np.tile(
            np.array(json.loads(row.replace(bytes("null", encoding='utf8'), bytes('0', encoding='utf8'))),
                     dtype=np.int32), (seq_len, 1)).T
        for i in range(feature_len):
            outputs[i][j] = feature_data[i, :]
        j += 1
    return outputs


def get_icf2(features_batch, batch_size, seq_len):
    global FEATURE_INFO_MAP
    feature_len = len(FEATURE_INFO_MAP['icf'])
    outputs = np.zeros((batch_size, seq_len, feature_len))
    i = 0
    for row in features_batch:
        outputs[i] = np.array(json.loads(row))
        i += 1
    return outputs


# get iv from input batch
def get_iv(features_batch, batch_size, seq_len):
    global FEATURE_INFO_MAP
    feature_len = len(FEATURE_INFO_MAP['iv'])
    outputs = np.zeros((batch_size, seq_len, feature_len))
    i = 0
    for row in features_batch:
        outputs[i] = np.array(json.loads(row))
        i += 1
    return outputs


# get pv from input batch
def get_pv(features_batch, batch_size, seq_len):
    global FEATURE_INFO_MAP
    feature_len = len(FEATURE_INFO_MAP['pv'])
    outputs = np.zeros((batch_size, seq_len, feature_len))
    i = 0
    for row in features_batch:
        outputs[i] = np.array(json.loads(row))
        i += 1
    return outputs


"""
@:return np.dstack
    >>> a = np.array((1,2,3))
    >>> b = np.array((2,3,4))
    >>> np.dstack((a,b))
    array([[[1, 2],
            [2, 3],
            [3, 4]]])
"""


# get iv and pv from input batch
def get_iv_and_pv(iv_batch, pv_batch, batch_size, seq_len):
    iv = get_iv(iv_batch, batch_size, seq_len)
    pv = get_pv(pv_batch, batch_size, seq_len)
    return np.dstack((iv, pv))


# get features from input batch
def get_features(uid_batch, ucf_batch, icf_batch, pv_batch, iv_batch, batch_size, seq_len):
    if FLAGS.model_type == 0:  # drr_base, see paper for more detail
        outputs = [get_pos(batch_size, seq_len), get_iv(iv_batch, batch_size, seq_len)]
        assert FLAGS.d_feature == len(FEATURE_INFO_MAP['iv'])
        return outputs
    elif FLAGS.model_type == 1:  # drr_personalized_v1, see paper for more detail
        outputs = [get_pos(batch_size, seq_len), get_uid(uid_batch, batch_size, seq_len)]
        outputs.extend(get_ucf(ucf_batch, batch_size, seq_len))
        outputs.extend(get_icf(icf_batch, batch_size, seq_len))
        outputs.append(get_iv(iv_batch, batch_size, seq_len))
        assert FLAGS.d_feature == len(FEATURE_INFO_MAP['iv'])
        return outputs
    elif FLAGS.model_type == 2:  # drr_personalized_v2, see paper for more detail
        # outputs = [get_pos(batch_size, seq_len), get_iv_and_pv(iv_batch, pv_batch, batch_size, seq_len)]
        outputs = [get_pos(batch_size, seq_len), np.dstack((get_icf2(icf_batch, batch_size, seq_len),
                                                            get_iv_and_pv(iv_batch, pv_batch, batch_size, seq_len)))]
        assert FLAGS.d_feature == len(FEATURE_INFO_MAP['icf']) + len(FEATURE_INFO_MAP['iv']) + len(FEATURE_INFO_MAP['pv'])
        return outputs


def input_generator(filename, batch_size, seq_len, repeat_cnt=-1):
    print("data_set={0} batch_size={1} seq_len={2} repeat_cnt={3} for input_generator".format(filename, batch_size,
                                                                                              seq_len, repeat_cnt))

    dataset = tf.data.experimental.CsvDataset([filename], record_defaults=[0, "", "", "", "", ""], field_delim='|') \
        .repeat(repeat_cnt).batch(batch_size)
    next_val = tf.compat.v1.data.make_one_shot_iterator(dataset).get_next()
    with K.get_session().as_default() as sess:
        while True:
            uid_batch, ucf_batch, icf_batch, iv_batch, pv_batch, label_batch = sess.run(next_val)
            yield get_features(uid_batch, ucf_batch, icf_batch, pv_batch, iv_batch, batch_size, seq_len), get_label(
                label_batch, batch_size, seq_len)


# get model
def get_model():
    model = None
    t = PRM(FLAGS.seq_len, FLAGS.d_feature, model_dim=FLAGS.d_model, inner_dim=FLAGS.d_inner_hid,
            n_head=FLAGS.n_head, key_dim=FLAGS.d_k, value_dim=FLAGS.d_v, blocks=FLAGS.n_layers, dropout=FLAGS.dropout)
    model = t.build()
    model.summary()
    print("model_type={0}".format(FLAGS.model_type))
    print(
        "model_setting:\n\tseq_len={0}\n\td_feature={1}\n\td_model={2}\n\td_inner_hid={3}\n\tn_head={4}\n\td_k={5}"
        "\n\td_v={6}\n\tn_layers={7}\n\tdropout={8}".format(
            FLAGS.seq_len, FLAGS.d_feature, FLAGS.d_model, FLAGS.d_inner_hid, FLAGS.n_head, FLAGS.d_k, FLAGS.d_v,
            FLAGS.n_layers, FLAGS.dropout))
    print("-" * 98)
    return model


class LRSchedulerPerStep(LearningRateSchedule, ABC):
    def __init__(self, d_model, warmup_steps=4000):
        super(LRSchedulerPerStep, self).__init__()

        self.d_model = d_model
        self.d_model = tf.cast(self.d_model, tf.float32)

        self.warmup_steps = warmup_steps

    def __call__(self, step):
        arg1 = tf.math.rsqrt(step)
        arg2 = step * (self.warmup_steps ** -1.5)

        return tf.math.rsqrt(self.d_model) * tf.math.minimum(arg1, arg2)


# train
def train():
    print("training....")
    if not os.path.exists(r"../test/logs"):
        os.mkdir(r"../test/logs")
        print("create log directory:{0}".format(r".\logs"))
    model = get_model()
    learning_rate = LRSchedulerPerStep(FLAGS.d_model)
    model.compile(loss='categorical_crossentropy',
                  optimizer=Adam(learning_rate=learning_rate, beta_1=0.9, beta_2=0.98, epsilon=1e-9),
                  metrics=['accuracy'])
    assert FLAGS.train_set != ""
    assert FLAGS.validation_set != ""
    print("train_set={0} validation_set={1} batch_size={2} seq_len={3}".format(FLAGS.train_set,
                                                                               FLAGS.validation_set, FLAGS.batch_size,
                                                                               FLAGS.seq_len))
    train_gen = input_generator(FLAGS.train_set, FLAGS.batch_size, FLAGS.seq_len)
    next(train_gen)
    validation_gen = input_generator(FLAGS.validation_set, FLAGS.batch_size, FLAGS.seq_len)
    next(validation_gen)
    print("saved_model_name={0} early_stop_patience={1} lr_per_step={2}".format(FLAGS.saved_model_name,
                                                                                FLAGS.early_stop_patience,
                                                                                FLAGS.lr_per_step))
    callback_list = [TensorBoard(log_dir=r"../test/logs"),
                     ModelCheckpoint(FLAGS.saved_model_name, verbose=1, monitor='val_loss', save_weights_only=True,
                                     save_best_only=True),
                     EarlyStopping(monitor='val_loss', patience=FLAGS.early_stop_patience, verbose=1)]
    print("train_epochs={0} train_steps_per_epoch={1} validation_steps={2}".format(FLAGS.train_epochs,
                                                                                   FLAGS.train_steps_per_epoch,
                                                                                   FLAGS.validation_steps))
    model.fit(train_gen, epochs=FLAGS.train_epochs, steps_per_epoch=FLAGS.train_steps_per_epoch,
              callbacks=callback_list, validation_data=validation_gen, validation_steps=FLAGS.validation_steps)
    K.clear_session()
    print("finish training!")


# predict
def predict():
    print("predicting...")
    if not os.path.exists(FLAGS.saved_model_name):
        print("the model file {0} does not exist!".format(FLAGS.saved_model_name))
        return
    else:
        print("load model from {0}!".format(FLAGS.saved_model_name))
    model = get_model()
    model.load_weights(FLAGS.saved_model_name)
    assert FLAGS.test_set != ""
    test_gen = input_generator(FLAGS.test_set, FLAGS.batch_size, FLAGS.seq_len, 1)
    batch_cnt = 0
    predict_output_file = "%s.predict.out" % FLAGS.test_set
    fout = open(predict_output_file, "w")

    """
    @test_batch
        [0]: List[ndarray] =>
            length: batch_size
            content:
                => personalized vector: [1, 2, ..., seq_len - 1]
                => [input vector, position vector]: seq_len * (iv_len + pv_len)
        [1]: ndarray =>
            label: [1 or 0 * seq_len]
    """

    try:
        for test_batch in test_gen:
            batch_cnt += 1
            features_batch = test_batch[0]
            label_batch = test_batch[1]
            predict_batch = model.predict_on_batch(features_batch)
            print("processed {0} batches...".format(batch_cnt))
            """
            @new_ranks: the indices that would sort the score list
                >>> x = np.array([3, 1, 2])
                >>> np.argsort(x)
                array([1, 2, 0])
            @new_labels: new sequence of the label list
            """
            for labels, predicts in zip(label_batch, predict_batch):
                if batch_cnt == 1:
                    print(predicts)
                if sum(labels) > 0:  # predict valid labels
                    new_ranks = np.argsort(-predicts)
                    new_labels = labels[new_ranks]
                    fout.write("%s\t%s\n" % (json.dumps(labels.tolist()), json.dumps(new_labels.tolist())))
    except tf.errors.OutOfRangeError:
        print("finish predicting!")
    fout.close()
    return 0


def main(_):
    beg_time = time.time()
    if FLAGS.train:
        train()
    else:
        predict()
        # get_model()
    time_cost = (time.time() - beg_time) / 60
    print("job done! time_cost={0} minutes".format(round(time_cost)))


if __name__ == "__main__":
    tf.compat.v1.app.run()
