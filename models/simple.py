#!/usr/bin/env python3  
# -*- coding: utf-8 -*-  
"""  
 @Desc:  
 @Author: Shane
 @Contact: iamshanesue@gmail.com  
 @Software: PyCharm  @since:python 3.6.4 
 @Created by Shane on 2018/5/28
 """

import tensorflow as tf
from tensorflow.contrib.rnn import LSTMCell, MultiRNNCell, GRUCell, DropoutWrapper

from models.rc_base import RcBase
from utils.log import logger


class Simple_model(RcBase):
    """
    """

    def create_model(self):
        num_layers = self.args.num_layers
        hidden_size = self.args.hidden_size
        cell = LSTMCell if self.args.use_lstm else GRUCell

        q_input = tf.placeholder(dtype = tf.int32, shape = [None, self.q_len], name = 'questions_bt')
        candidate_idxs = tf.placeholder(dtype = tf.int32, shape = [None, self.dataset.A_len], name = 'candidates_bi')
        d_input = tf.placeholder(dtype = tf.int32, shape = [None, self.d_len], name = 'documents_bt')

        y_true_idx = tf.placeholder(dtype = tf.float32, shape = [None, self.dataset.A_len], name = 'y_true_bi')

        init_embed = tf.constant(self.embedding_matrix, dtype = tf.float32)
        embedding_matrix = tf.get_variable(name = 'embdding_matrix', initializer = init_embed, dtype = tf.float32)

        q_real_len = tf.reduce_sum(tf.sign(tf.abs(q_input)), axis = 1)
        d_real_len = tf.reduce_sum(tf.sign(tf.abs(d_input)), axis = 1)
        d_mask = tf.sequence_mask(dtype = tf.float32, maxlen = self.d_len, lengths = d_real_len)

        with tf.variable_scope('q_encoder') as scp:
            q_embed = tf.nn.embedding_lookup(embedding_matrix, q_input)

            q_rnn_f = MultiRNNCell(
                cells = [DropoutWrapper(cell(hidden_size), output_keep_prob = self.args.keep_prob) for _ in range(num_layers)])
            q_rnn_b = MultiRNNCell(
                cells = [DropoutWrapper(cell(hidden_size), output_keep_prob = self.args.keep_prob) for _ in range(num_layers)])

            outputs, last_states = tf.nn.bidirectional_dynamic_rnn(cell_fw = q_rnn_f, cell_bw = q_rnn_b, inputs = q_embed,
                                                                   sequence_length = q_real_len, initial_state_bw = None,
                                                                   dtype = "float32", parallel_iterations = None,
                                                                   swap_memory = True, time_major = False, scope = None)

            # last_states -> (output_state_fw, output_state_bw)
            q_emb_bi = tf.concat(outputs, axis = -1)
            logger("q_encoded_bf shape {}".format(q_emb_bi.get_shape()))

        with tf.variable_scope('d_encoder'):
            d_embed = tf.nn.embedding_lookup(embedding_matrix, d_input)

            d_rnn_f = MultiRNNCell(
                cells = [DropoutWrapper(cell(hidden_size), output_keep_prob = self.args.keep_prob) for _ in range(num_layers)])
            d_rnn_b = MultiRNNCell(
                cells = [DropoutWrapper(cell(hidden_size), output_keep_prob = self.args.keep_prob) for _ in range(num_layers)])

            d_rnn_out, last_states = tf.nn.bidirectional_dynamic_rnn(cell_bw = d_rnn_b, cell_fw = d_rnn_f, inputs = d_embed,
                                                                     sequence_length = d_real_len, swap_memory = True,dtype="float32",)

            d_emb_bi = tf.concat(d_rnn_out, axis = -1)
            logger("d_encoded_bf shape {}".format(d_emb_bi.get_shape()))

        def atten(x):
            """
            :param x: is a tuple which contain shape (None, max_time, hidden_size) (None, hidden_size)
            :return:
            """
            atten = tf.matmul(d_emb_bi, tf.expand_dims(x, -1), adjoint_a = False, adjoint_b = False)
            return tf.reshape(atten, [-1, self.d_len])

        with tf.variable_scope('attention_dq'):
            atten_d_q = tf.matmul(d_emb_bi, q_emb_bi, adjoint_b = True)
            atten_d = tf.reduce_sum(atten_d_q, axis = -1)
            attened_d_masked = tf.multiply(atten_d, d_mask, name = 'attened_d_masked')
            attened_softmax = tf.nn.softmax(logits = attened_d_masked, name = 'attened_d_softmax', dim = -1)

            # there should be [None, seq_len, hidden_size]
            attened_d = tf.multiply(d_emb_bi, tf.expand_dims(attened_softmax, -1))

        def candidate_score(x):
            context, cand = x
            score = tf.matmul(cand, context, adjoint_b = True)  # [None, seq_len, 1)
            score_sum = tf.reduce_mean(score, axis = -1)
            return score_sum

        with tf.variable_scope('candidate'):
            candi_embed = tf.nn.embedding_lookup(params = embedding_matrix, ids = candidate_idxs)
            # [None, can_len, 1]
            candi_score_d = tf.matmul(candi_embed, attened_d, transpose_b = True)
            candi_score = tf.reduce_mean(candi_score_d, axis = -1)
            candi_score_sfm = tf.nn.softmax(logits = candi_score, name = 'candi_score_sfm', dim = -1)

        self.loss = tf.reduce_mean(-tf.reduce_sum(y_true_idx * tf.log(candi_score_sfm), axis = -1))
        self.correct_prediction = tf.reduce_sum(tf.sign(tf.cast(tf.equal(tf.argmax(y_true_idx, 1), tf.argmax(candi_score_sfm, 1)), 'float')))
